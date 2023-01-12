#!/usr/bin/env cwl-runner
class: CommandLineTool
cwlVersion: v1.0

label: Returns a dictionary of the given arguments as a JSON-encoded string.
doc: |-
  Returns a dictionary of the given arguments as a JSON-encoded string.

baseCommand: echo # Anything, unused

requirements:
  InlineJavascriptRequirement: {}

inputs:
  config: # NOTE: This input name is special in the compiler.
  # The compiler will automatically convert the literal dict into a JSON-encoded string.
    label: A dictionary of the given arguments as a JSON-encoded string.
    doc: |-
      A dictionary of the given arguments as a JSON-encoded string.
    type: string
    format:
    - edam:format_2330
    default: "{}" # And this will JSON.parse() to an empty dict. See below.

  nstlim:
    label: The number of timesteps
    doc: |-
      The number of timesteps
    type: int

  dt:
    label: The length of each timestep
    doc: |-
      The length of each timestep
    type: float

  temp0:
    label: The nominal temperature
    doc: |-
      The nominal temperature
    type: float

  pres0:
    label: The nominal pressure
    doc: |-
      The nominal pressure
    type: float

  output_config_string:
    label: A dictionary of the given arguments as a JSON-encoded string.
    doc: |-
      A dictionary of the given arguments as a JSON-encoded string.
    type: string?
    format:
    - edam:format_2330

outputs:
  output_config_string:
    label: A dictionary of the given arguments as a JSON-encoded string.
    doc: |-
      A dictionary of the given arguments as a JSON-encoded string.
    type: string
    #format: edam:format_2330 # "'str' object does not support item assignment""
    outputBinding:
      outputEval: |
        ${
          var config = JSON.parse(inputs.config);
          if (("mdin" in config) === false) {
            config["mdin"] = {}; // Initialize it
          }
          // TODO: Check for duplicate keys, i.e.
          // "Pressure coupling incorrect number of values (I need exactly 1)"
          config["mdin"]["nstlim"] = inputs.nstlim;
          config["mdin"]["dt"] = inputs.dt;
          config["mdin"]["temp0"] = inputs.temp0 //Javascript interprets dash as subtract...
          config["mdin"]["pres0"] = inputs.pres0;
          return JSON.stringify(config);
        }

$namespaces:
  edam: https://edamontology.org/

$schemas:
- https://raw.githubusercontent.com/edamontology/edamontology/master/EDAM_dev.owl
