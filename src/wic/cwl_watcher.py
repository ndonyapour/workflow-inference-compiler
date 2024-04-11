import argparse
import glob
import json
import os
import subprocess as sub
import sys
import time
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

import graphviz
import networkx as nx
from jsonschema import Draft202012Validator

from . import input_output as io
from . import ast, cli, compiler, inference, utils
from .run_local import stage_input_files
from .plugins import get_tools_cwl, get_yml_paths, logging_filters
from .schemas import wic_schema
from .wic_types import GraphData, GraphReps, Json, StepId, Tools, YamlTree

# from watchdog.observers import Observer
# from watchdog.observers.polling import PollingObserver
# from watchdog.events import FileSystemEvent, PatternMatchingEventHandler


def absolute_paths(config: Json, cachedir_path: Path) -> Json:
    """Recursively searches for paths in config and makes them absolute by prepending cachedir_path.

    Args:
        config (Json): The contents of the YAML cwl_watcher config: tag.
        cachedir_path (Path): The --cachedir directory of the main workflow.

    Returns:
        Json: The contents of the YAML cwl_watcher config: tag, with all paths prepended with cachedir_path.
    """
    new_json: Json = {}
    for key, val in config.items():
        if isinstance(val, Dict):
            new_val = absolute_paths(val, cachedir_path)
        else:
            new_val = val
            # TODO: Improve this heuristic
            if 'input' in key and 'path' in key:
                new_val = str(cachedir_path / val)  # type: ignore
                changed_files = file_watcher_glob(cachedir_path, val, {})
                # We require unique filenames, so there should only be one file.
                # (except for files that get created within the cwl_watcher workflow itself)
                changed_files_lst = list(changed_files.items())
                if len(changed_files_lst) == 0:
                    print(f'Warning! Changed files should be length one! {val}\n{changed_files_lst}')
                else:
                    if len(changed_files_lst) != 1:
                        print(f'Warning! Changed files should be length one! {val}\n{changed_files_lst}')
                    changed_files_lst.sort(key=lambda x: x[1])
                    file = changed_files_lst[-1][0]  # most recent
                    new_val = str(Path(file).absolute())  # type: ignore
        new_json[key] = new_val
    return new_json


def rerun_cwltool(homedir: str, _directory_realtime: Path, cachedir_path: Path, cwl_tool: str,
                  args_vals: Json, tools_cwl: Tools, yml_paths: Dict[str, Dict[str, Path]],
                  validator: Draft202012Validator, root_workflow_yml_path: Path) -> None:
    """This will speculatively execute cwltool for real-time analysis purposes.\n
    It will NOT check for return code 0. See docs/userguide.md

    Args:
        homedir (str): The users home directory
        _directory_realtime (Path): The working directory of the main workflow.\n
        Currently unused to avoid this workflow from overwriting files from the main\n
        workflow (which by design will likely be running concurrently with this code).
        cachedir_path (Path): The --cachedir directory of the main workflow.
        cwl_tool (str): The CWL CommandLineTool or YAML filename (without extension).
        args_vals (Json): The contents of the YAML cwl_watcher config: tag.
        tools_cwl (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()
        yml_paths (Dict[str, Dict[str, Path]]): The yml workflow definitions found using get_yml_paths()
        validator (Draft202012Validator): Used to validate the yml files against the autogenerated schema.
        root_workflow_yml_path (Path): The full absolute path to the root workflow yml file.
    """
    try:
        # Make paths in arguments absolute w.r.t the realtime directory. See below.
        args_vals_new = absolute_paths(args_vals, cachedir_path)

        # Construct a single-step workflow and add its arguments
        # import yaml
        if Path(cwl_tool).suffix == '.wic':
            yaml_path = cwl_tool
            wic_steps = {'steps': {f'(1, {cwl_tool})': {'wic': {'steps': args_vals_new}}}}
            root_yaml_tree = {'wic': wic_steps, 'steps': [{cwl_tool: None}]}
            # print('root_yaml_tree')
            # print(yaml.dump(root_yaml_tree))
            # TODO: Support other namespaces
            plugin_ns = 'global'  # wic['wic'].get('namespace', 'global')
            step_id = StepId(yaml_path, plugin_ns)
            y_t = YamlTree(step_id, root_yaml_tree)
            yaml_tree_raw = ast.read_ast_from_disk(homedir, y_t, yml_paths, tools_cwl, validator, True)
            yaml_tree = ast.merge_yml_trees(yaml_tree_raw, {}, tools_cwl)
            yaml_tree = ast.python_script_generate_cwl(yaml_tree, Path(''), tools_cwl)
            yml = yaml_tree.yml
        else:
            yml = {'steps': [{cwl_tool: args_vals_new}]}
        # print('yml')
        # print(yml)
        # print(yaml.dump(yml))

        # Measure compile time
        time_initial = time.time()

        # Setup dummy args
        testargs = ['wic', '--yaml', '', '--cwl_output_intermediate_files', 'True']  # ignore --yaml
        # For now, we need to enable --cwl_output_intermediate_files. See comment in compiler.py
        with patch.object(sys, 'argv', testargs):
            args = cli.parser.parse_args()

        # TODO: Support other namespaces
        plugin_ns = 'global'  # wic['wic'].get('namespace', 'global')
        yaml_path = f'{cwl_tool}_only.wic'
        stepid = StepId(yaml_path, plugin_ns)
        yaml_tree = YamlTree(stepid, yml)
        subgraph = GraphReps(graphviz.Digraph(name=yaml_path), nx.DiGraph(), GraphData(yaml_path))
        compiler_info = compiler.compile_workflow(yaml_tree, args, [], [subgraph], {}, {}, {}, {},
                                                  tools_cwl, True, relative_run_path=False, testing=False)
        rose_tree = compiler_info.rose
        working_dir = Path('.') / Path('autogenerated/')  # Use a new working directory.
        # Can also use `_directory_realtime` / Path('autogenerated/') at the risk of overwriting other files.
        io.write_to_disk(rose_tree, working_dir, relative_run_path=False)

        time_final = time.time()
        print(f'compile time for {cwl_tool}: {round(time_final - time_initial, 4)} seconds')

        yaml_inputs = rose_tree.data.workflow_inputs_file
        stage_input_files(yaml_inputs, root_workflow_yml_path, relative_run_path=False, throw=False)

        # NOTE: Since we are running cwltool 'within' cwltool, the inner
        # cwltool command will get run from working_dir, but then cwl_tool
        # will run within some other hashed directory in .../cachedir/
        # The solution is to modify the input paths above to be absolute.
        # The easiest way to do this for now is recompiling. This adds a few
        # seconds, but most of the time will be CWL validation and runtime.
        # Alternatively, we could try to compile once in main() and then
        # make the paths absolute in f'{cwl_tool}_only_inputs.yml' here.
        cmd: List[str] = ['cwltool', '--cachedir', str(cachedir_path),
                          f'{cwl_tool}_only.cwl', f'{cwl_tool}_only_inputs.yml']
        # proc = sub.run(self.cmd, cwd=working_dir)
        # cmd = self.cmd
        print('Running', cmd)
        proc = sub.run(cmd, cwd=working_dir, check=False)  # See below!
        print('inner cwltool completed')
        # Don't check the return code because the file may not exist yet, or
        # because speculative execution may fail for any number of reasons.
        # proc.check_returncode()
    except FileNotFoundError as e:
        # The file may not exist yet.
        print(e)


# NOTE: You should be very careful when using file watchers! Most libraries
# (watchdog, watchfiles, etc) will use operating system / platform-specific
# APIs to check for changes (for performance reasons). However, this can cause
# problems in some cases, specifically for network drives.
# See https://stackoverflow.com/questions/45441623/using-watchdog-of-python-to-monitoring-afp-shared-folder-from-linux
# I'm 99% sure the same problem happens with Docker containers. Either way, the
# solution is to use polling. However, for unknown reasons, simply replacing
# Observer with PollingObserver doesn't seem to work! So we are forced to write
# our own basic file watcher using glob.


# class SubprocessHandler(PatternMatchingEventHandler):

#     def __init__(self, cmd: List[str], cachedir_path: str, cwl_tool: str, args_vals: Json, tools_cwl: Tools, **kwargs: Any) -> None:
#         self.cmd = cmd
#         self.lock = False
#         self.cachedir_path = cachedir_path
#         self.cwl_tool = cwl_tool
#         self.args_vals = args_vals
#         self.tools_cwl = tools_cwl
#         super().__init__(**kwargs)

#     def on_any_event(self, event: FileSystemEvent) -> None:
#         # Use a lock to prevent us from DOS'ing ourselves
#         global lock
#         if event.event_type == 'modified' and not lock:
#             directory = Path(event._src_path).parent
#             print('directory', directory)
#             # self.lock = True
#             print(event)
#             rerun_cwltool(directory, self.cachedir_path, self.cwl_tool, self.args_vals, self.tools_cwl)
#             # self.lock = False


def file_watcher_glob(cachedir_path: Path, pattern: str, prev_files: Dict[str, float]) -> Dict[str, float]:
    """Determines whether files (specified by the given glob pattern) have been either recently created or modified.\n
    Note that this is a workaround due to an issue with using standard file-watching libraries.

    Args:
        cachedir_path (Path): The --cachedir directory of the main workflow.
        pattern (str): The glob pattern which specifies the files to be watched.
        prev_files (Dict[str, float]): This should be the return value from the previous function call.

    Returns:
        Dict[str, float]: A dictionary containing the filepaths and last modification times.
    """
    changed_files = {}
    file_pattern = str(cachedir_path / f'**/{pattern}')
    file_paths = glob.glob(file_pattern, recursive=True)
    for file in file_paths:
        mtime = os.path.getmtime(file)
        if file not in prev_files:
            # created
            changed_files[file] = mtime
        elif mtime > prev_files[file]:
            # modified
            changed_files[file] = mtime
    return changed_files


def cli_watcher() -> argparse.Namespace:
    """This contains the command line arguments for speculative execution.

    Returns:
        argparse.Namespace: The command line arguments
    """
    parser = argparse.ArgumentParser(prog='main', description='Speculatively execute a high-level yaml workflow file.')
    parser.add_argument('--cwl_tool', type=str, required=True,
                        help='CWL or WIC filestem')
    parser.add_argument('--cachedir_path', type=str, required=True,
                        help='This should be set to the --cachedir option from the main cli')
    parser.add_argument('--file_pattern', type=str, required=True,
                        help='This glob pattern is used to find files within --cachedir_path')
    parser.add_argument('--max_times', type=str, required=True,
                        help='--cwl_tool will be speculatively executed at most max_times')
    parser.add_argument('--config', type=str, required=True,
                        help='This should be a json-encoded representation of the config: YAML subtag of --cwl_tool')
    parser.add_argument('--homedir', type=str, required=False,  # default=str(Path().home()), # NOTE: no default!
                        help='The users home directory. This is necessary because CWL clears environment variables (e.g. HOME)')
    parser.add_argument('--root_workflow_yml_path', type=str, required=True,
                        help='The full absolute path to the root workflow yml file.')
    return parser.parse_args()


def main() -> None:
    """See docs/userguide.md#real-time-analysis--speculative-execution"""
    print('cwl_watcher sys.argv', sys.argv)
    args = cli_watcher()
    logging_filters()

    cachedir_path = Path(args.cachedir_path)
    file_pattern = args.file_pattern
    cwl_tool = args.cwl_tool
    max_times = int(args.max_times)
    root_workflow_yml_path = Path(args.root_workflow_yml_path)

    # Create an empty 'logfile' so that cwl_watcher.cwl succeeds.
    # TODO: Maybe capture cwl_tool stdout/stderr and redirect to this logfile.
    logfile = Path(f'{cwl_tool}_only.log')
    logfile.touch()

    args_vals = json.loads(args.config)
    # In CWL all env variables are hidden by default so Path().home() doesn't work
    # Also User may specify a different homedir
    default_config_file = Path(args.homedir)/'wic'/'global_config.json'
    global_config: Json = io.get_config(Path(args.config_file), default_config_file)

    tools_cwl = get_tools_cwl(global_config, quiet=args.quiet)
    yml_paths = get_yml_paths(global_config)

    # Perform initialization via mutating global variables (This is not ideal)
    compiler.inference_rules = global_config.get('inference_rules', {})
    inference.renaming_conventions = global_config.get('renaming_conventions', [])

    # Generate schemas for validation
    yaml_stems = utils.flatten([list(p) for p in yml_paths.values()])
    validator = wic_schema.get_validator(tools_cwl, yaml_stems)

    cachedir_hash_path = Path('.').absolute()
    print('cachedir_hash_path', cachedir_hash_path)

    """cmd: List[str] = ['cwltool', '--cachedir', cachedir_path,
                         f'{cachedir_hash_path}/{cwl_tool}_only.cwl',
                         f'{cachedir_hash_path}/{cwl_tool}_only_inputs.yml']
    event_handler = SubprocessHandler(cmd, cachedir_path, cwl_tool, args_vals, tools_cwl, patterns=[file_pattern])
    observer = PollingObserver()  # This does not work!
    observer.schedule(event_handler, cachedir_path, recursive=True)
    observer.start()"""

    # Specify a maximum number of iterations to guarantee termination.
    # Total runtime will be (sleep time + compile time + run time) * max_iters
    # For now, there is no way to estimate max_iters such that polling will end
    # around the same time as the original workflow step.
    # TODO: Generate a file when the original workflow step finishes, and look
    # for that file here to terminate. Keep max_iters just in case.
    i = 0
    prev_files: Dict[str, float] = {}
    try:
        while i < max_times:
            # Use our own polling file watcher, see above.
            changed_files = file_watcher_glob(cachedir_path, file_pattern, prev_files)
            # print('len(changed_files)', len(changed_files))
            for file in changed_files:
                if file_pattern[1:] in file:
                    print(file)
                    rerun_cwltool(args.homedir, Path(file).parent, cachedir_path, cwl_tool,
                                  args_vals, tools_cwl, yml_paths, validator,
                                  root_workflow_yml_path)
            prev_files = {**prev_files, **changed_files}

            time.sleep(1.0)  # Wait at least 1 second so we don't just spin.
            i += 1
    except KeyboardInterrupt:
        pass
    # observer.stop()
    # observer.join()

    failed = False  # Your analysis goes here
    if failed:
        print(f'{cwl_tool} failed!')
        sys.exit(1)


if __name__ == "__main__":
    main()
