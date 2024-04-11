import uuid
import copy
from pathlib import Path
import sys
import traceback
from typing import Dict, List

from mergedeep import merge, Strategy
from jsonschema import Draft202012Validator
import yaml

from . import python_cwl_adapter, utils
from .wic_types import Yaml, Tools, YamlTree, YamlForest, StepId, Tool
from wic.utils_yaml import wic_loader

# NOTE: AST = Abstract Syntax Tree


def read_ast_from_disk(homedir: str,
                       yaml_tree_tuple: YamlTree,
                       yml_paths: Dict[str, Dict[str, Path]],
                       tools: Tools,
                       validator: Draft202012Validator,
                       ignore_validation_errors: bool) -> YamlTree:
    """Reads the yml workflow definition files from disk (recursively) and inlines them into an AST

    Args:
        homedir (str): The users home directory
        yaml_tree_tuple (YamlTree): A tuple of a filepath and its Yaml file contents.
        yml_paths (Dict[str, Dict[str, Path]]): The yml workflow definitions found using get_yml_paths()
        tools (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()
        validator (Draft202012Validator): Used to validate the yml files against the autogenerated schema.
        ignore_validation_errors (bool): Temporarily ignore validation errors. Do not use this permanently!

    Raises:
        Exception: If the yml file(s) do not exist

    Returns:
        YamlTree: A tuple of the root filepath and the associated yml AST
    """
    (step_id, yaml_tree) = yaml_tree_tuple

    try:
        if not ignore_validation_errors:
            validator.validate(yaml_tree)
    except Exception as e:
        yaml_path = Path(step_id.stem)
        print('Failed to validate', yaml_path)
        print(f'See validation_{yaml_path.stem}.txt for detailed technical information.')
        # Do not display a nasty stack trace to the user; hide it in a file.
        with open(f'validation_{yaml_path.stem}.txt', mode='w', encoding='utf-8') as f:
            # https://mypy.readthedocs.io/en/stable/common_issues.html#python-version-and-system-platform-checks
            if sys.version_info >= (3, 10):
                traceback.print_exception(type(e), value=e, tb=None, file=f)
            else:
                traceback.print_exception(etype=type(e), value=e, tb=None, file=f)
        sys.exit(1)

    wic = {'wic': yaml_tree.get('wic', {})}
    if 'backends' in wic['wic']:
        # Recursively expand each backend, but do NOT choose a specific backend.
        # Require back_name to be .wic? For now, yes.
        backends_trees = []
        for back_name, back in wic['wic']['backends'].items():
            plugin_ns = wic['wic'].get('namespace', 'global')
            stepid = StepId(back_name, plugin_ns)
            backends_tree = read_ast_from_disk(homedir, YamlTree(stepid, back), yml_paths, tools, validator,
                                               ignore_validation_errors)
            backends_trees.append(backends_tree)
        yaml_tree['wic']['backends'] = dict(backends_trees)
        return YamlTree(step_id, yaml_tree)

    steps: List[Yaml] = yaml_tree['steps']
    wic_steps = wic['wic'].get('steps', {})
    steps_keys = utils.get_steps_keys(steps)
    tools_stems = [stepid.stem for stepid in tools]
    subkeys = utils.get_subkeys(steps_keys, tools_stems)

    for i, step_key in enumerate(steps_keys):
        stem = Path(step_key).stem

        # Recursively read subworkflows, adding yml file contents
        if step_key in subkeys:
            # Check for namespaceing; otherwise use the namespace 'global'.
            # NOTE: For now, do not support overloading / parameter passing for
            # namespaces, because we would have to call merge_yml_trees here.
            # It could (easily?) be done, but right now we have excellent
            # separation of concerns between simply reading yml files from disk
            # and then performing AST transformations in-memory.
            sub_wic = wic_steps.get(f'({i+1}, {step_key})', {})
            plugin_ns = sub_wic.get('wic', {}).get('namespace', 'global')

            paths_ns_i = yml_paths.get(plugin_ns, {})
            if paths_ns_i == {}:
                wicdir = Path(homedir) / 'wic'
                raise Exception(
                    f"Error! namespace {plugin_ns} not found in yaml paths. Check 'search_paths_wic' in your config file")
            if stem not in paths_ns_i:
                msg = f'Error! {stem} not found in namespace {plugin_ns} when attempting to read {step_id.stem}.wic'
                if stem == 'in':
                    msg += f'\n(Check that you have properly indented the `in` tag in {step_id.stem})'
                raise Exception(msg)
            yaml_path = paths_ns_i[stem]

            if not (yaml_path.exists() and yaml_path.suffix == '.wic'):
                raise Exception(f'Error! {yaml_path} does not exist or is not a .wic file.')

            # Load the high-level yaml sub workflow file.
            with open(yaml_path, mode='r', encoding='utf-8') as y:
                sub_yaml_tree_raw: Yaml = yaml.load(y.read(), Loader=wic_loader())

            y_t = YamlTree(StepId(step_key, plugin_ns), sub_yaml_tree_raw)
            (step_id_, sub_yml_tree) = read_ast_from_disk(homedir, y_t, yml_paths, tools, validator,
                                                          ignore_validation_errors)

            step_i_dict = {} if steps[i][step_key] is None else steps[i][step_key]
            # Do not merge these two dicts; use subtree and parentargs so we can
            # apply subtree before compilation and parentargs after compilation.
            steps[i][step_key] = {'subtree': sub_yml_tree, 'parentargs': step_i_dict}

    return YamlTree(step_id, yaml_tree)


def merge_yml_trees(yaml_tree_tuple: YamlTree,
                    wic_parent: Yaml,
                    tools: Tools) -> YamlTree:
    """Implements 'parameter passing' by recursively merging wic: yml tags.
    Values from the parent workflow will overwrite / override subworkflows.
    See https://github.com/PolusAI/mm-workflows/blob/main/examples/gromacs/basic.wic for details

    Args:
        yaml_tree_tuple (YamlTree): A tuple of a name and a yml AST
        wic_parent (Yaml): The wic: yml dict from the parent workflow
        tools (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()

    Raises:
        Exception: If a wic: tag is found as an argument to a CWL CommandLineTool

    Returns:
        YamlTree: The yml AST with all wic: tags recursively merged.
    """
    (step_id, yaml_tree) = yaml_tree_tuple

    # Check for top-level yml dsl args
    wic_self = {'wic': yaml_tree.get('wic', {})}
    wic = merge(wic_self, wic_parent, strategy=Strategy.TYPESAFE_REPLACE)
    # Here we want to ADD wic: as a top-level yaml tag.
    # In the compilation phase, we want to remove it.
    yaml_tree['wic'] = wic['wic']
    wic_steps = wic['wic'].get('steps', {})

    if 'backends' in wic['wic']:
        # Recursively expand each backend, but do NOT choose a specific backend.
        # Require back_name to be .wic? For now, yes.
        backends_trees = []
        for stepid, back in wic['wic']['backends'].items():
            backends_tree = merge_yml_trees(YamlTree(stepid, back), wic_parent, tools)
            backends_trees.append(backends_tree)
        yaml_tree['wic']['backends'] = dict(backends_trees)
        return YamlTree(step_id, yaml_tree)

    steps: List[Yaml] = yaml_tree['steps']
    steps_keys = utils.get_steps_keys(steps)
    tools_stems = [stepid.stem for stepid in tools]
    subkeys = utils.get_subkeys(steps_keys, tools_stems)

    for i, step_key in enumerate(steps_keys):
        # Recursively merge subworkflows, to implement parameter passing.
        if step_key in subkeys:
            # Extract the sub yaml file that we pre-loaded from disk.
            sub_yml_tree_initial = steps[i][step_key]['subtree']
            sub_wic = wic_steps.get(f'({i+1}, {step_key})', {})

            y_t = YamlTree(StepId(step_key, step_id.plugin_ns), sub_yml_tree_initial)
            (step_key_, sub_yml_tree) = merge_yml_trees(y_t, sub_wic, tools)
            # Now mutably overwrite the self args with the merged args
            steps[i][step_key]['subtree'] = sub_yml_tree

        # Extract provided CWL args, if any, and (recursively) merge them with
        # provided CWL args passed in from the parent, if any.
        # (At this point, any DSL args provided from the parent(s) should have
        # all of the initial yml tags removed, leaving only CWL tags remaining.)
        if step_key not in subkeys:
            clt_args = wic_steps.get(f'({i+1}, {step_key})', {})
            if 'wic' in clt_args:
                # Do NOT add yml tags to the raw CWL!
                # We can simply leave any step-specific wic: tags at top-level.
                # Copy so we only delete from the step, not also the top-level.
                clt_args = copy.deepcopy(clt_args)
                del clt_args['wic']
            sub_yml_tree = clt_args
            args_provided_dict_self = {}
            if steps[i][step_key]:
                args_provided_dict_self = steps[i][step_key]
            # NOTE: To support overloading, the parent args must overwrite the child args!
            args_provided_dict = merge(args_provided_dict_self, sub_yml_tree,
                                       strategy=Strategy.TYPESAFE_REPLACE)  # TYPESAFE_ADDITIVE ?
            # Now mutably overwrite the self args with the merged args
            steps[i][step_key] = args_provided_dict

    return YamlTree(step_id, yaml_tree)


def tree_to_forest(yaml_tree_tuple: YamlTree, tools: Tools) -> YamlForest:
    """The purpose of this function is to abstract away the process of traversing an AST.

    Args:
        yaml_tree_tuple (YamlTree): A tuple of name and yml AST
        tools (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()

    Returns:
        YamlForest: A recursive data structure containing all sub-trees encountered while traversing the yml AST.
    """
    (step_id, yaml_tree) = yaml_tree_tuple

    wic = {'wic': yaml_tree.get('wic', {})}
    if 'backends' in wic['wic']:
        backends_forest_list = []
        for stepid, back in wic['wic']['backends'].items():
            backend_forest = (stepid, tree_to_forest(YamlTree(stepid, back), tools))
            backends_forest_list.append(backend_forest)
        return YamlForest(YamlTree(step_id, yaml_tree), backends_forest_list)

    steps: List[Yaml] = yaml_tree['steps']
    wic_steps = wic['wic'].get('steps', {})
    steps_keys = utils.get_steps_keys(steps)
    tools_stems = [stepid.stem for stepid in tools]
    subkeys = utils.get_subkeys(steps_keys, tools_stems)

    yaml_forest_list = []

    for i, step_key in enumerate(steps_keys):

        if step_key in subkeys:
            wic_step_i = wic_steps.get(f'({i+1}, {step_key})', {})
            plugin_ns_i = wic_step_i.get('wic', {}).get('namespace', 'global')

            sub_yaml_tree = steps[i][step_key]['subtree']
            sub_yml_forest = tree_to_forest(YamlTree(StepId(step_key, plugin_ns_i), sub_yaml_tree), tools)
            (sub_yml_tree_step_id, sub_yml_tree_) = sub_yml_forest.yaml_tree
            yaml_forest_list.append((sub_yml_tree_step_id, sub_yml_forest))

    return YamlForest(YamlTree(step_id, yaml_tree), yaml_forest_list)


def python_script_generate_cwl(yaml_tree_tuple: YamlTree,
                               root_yml_dir_abs: Path,
                               tools: Tools) -> YamlTree:
    """Generates a CWL CommandLineTool for each python_script: tag,
    mutably adds them to tools, and updates the call sites in yaml_tree.

    Args:
        yaml_tree_tuple (YamlTree): A tuple of a name and a yml AST
        root_yml_dir_abs (Path): The absolute path to the directory containing the root workflow yml file
        tools (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()

    Returns:
        YamlTree: The yml AST with all python_script tags replaced with references to the auto-generated CWL.
    """
    (step_id, yaml_tree) = yaml_tree_tuple

    wic = {'wic': yaml_tree.get('wic', {})}

    if 'backends' in wic['wic']:
        backends_trees = []
        for stepid, back in wic['wic']['backends'].items():
            backends_tree = python_script_generate_cwl(YamlTree(stepid, back), root_yml_dir_abs, tools)
            backends_trees.append(backends_tree)
        yaml_tree['wic']['backends'] = dict(backends_trees)
        return YamlTree(step_id, yaml_tree)

    steps: List[Yaml] = yaml_tree['steps']
    steps_keys = utils.get_steps_keys(steps)
    tools_stems = [stepid.stem for stepid in tools]
    subkeys = utils.get_subkeys(steps_keys, tools_stems)

    for i, step_key in enumerate(steps_keys):
        if step_key in subkeys:
            sub_yml_tree_initial = steps[i][step_key]['subtree']
            y_t = YamlTree(StepId(step_key, step_id.plugin_ns), sub_yml_tree_initial)
            (step_key_, sub_yml_tree) = python_script_generate_cwl(y_t, root_yml_dir_abs, tools)
            steps[i][step_key]['subtree'] = sub_yml_tree

        if step_key not in subkeys:
            if 'python_script' == step_key:
                # This generates a CWL CommandLineTool for an arbitrary python script.
                yml_args = copy.deepcopy(steps[i][step_key]['in'])
                python_script_path = yml_args.get('script', '')
                if isinstance(python_script_path, dict) and 'wic_inline_input' in python_script_path:
                    python_script_path = python_script_path['wic_inline_input']
                # NOTE: The existence of the script: tag should now be guaranteed in the schema
                del yml_args['script']
                python_script_docker_pull = yml_args.get('dockerPull', '')  # Optional
                if isinstance(python_script_docker_pull, dict) and 'wic_inline_input' in python_script_docker_pull:
                    python_script_docker_pull = python_script_docker_pull['wic_inline_input']
                if 'dockerPull' in yml_args:
                    del yml_args['dockerPull']
                    del steps[i][step_key]['in']['dockerPull']
                python_script_path = root_yml_dir_abs / Path(python_script_path)
                python_script_mod = Path(python_script_path).name[:-3]
                module = python_cwl_adapter.get_module(python_script_mod, python_script_path, yml_args)
                generated_cwl = python_cwl_adapter.generate_CWL_CommandLineTool(
                    module.inputs, module.outputs, python_script_docker_pull)
                # See https://docs.python.org/3/library/uuid.html#uuid.uuid4
                # "If all you want is a unique ID, you should probably call uuid1() or uuid4()"
                unique_id = 'python_script_' + str(uuid.uuid4())
                # TODO: use the trick from the copy_cwl_tools branch to keep
                # programmatically modified (and in this case, generated from scratch)
                # CWL CommandLineTools in-memory so we can defer writing to disk
                filepath = 'autogenerated/' + unique_id + '.cwl'
                with open(filepath, mode='w', encoding='utf-8') as f:
                    f.write(yaml.dump(generated_cwl, sort_keys=False, line_break='\n', indent=2))

                # Now replace step_key with unique_id in the workflow
                steps[i] = {unique_id: steps[i][step_key]}
                # and add the auto-generated CWL CommandLineTool to tools
                step_id_ = StepId(unique_id, 'global')
                tool_i = Tool(filepath, generated_cwl)
                tools[step_id_] = tool_i

    return YamlTree(step_id, yaml_tree)
