#!/usr/bin/env cwl-runner
cwlVersion: v1.0

class: CommandLineTool

label: Run a python3 script

doc: |-
  Run a python3 script

baseCommand: python3

hints:
  DockerRequirement:
    dockerPull: ndonyapour/scripts

inputs:
  script:
    type: string
    inputBinding:
      position: 1

  input_pdb_path:
    type: File
    format:
    - edam:format_1476 # pdb
    inputBinding:
      position: 2

  output_pdb_path:
    label: Path to the output file
    doc: |-
      Path to the output file
    type: string
    format:
    - edam:format_1476 # pdb
    inputBinding:
      position: 3
    default: system.pdb

  ligand_residue_name:
    label: The residue name of ligand
    doc: |-
      The residue name of ligand
    type: string
    format:
    - edam:format_2330
    inputBinding:
      position: 4
    default: MOL

outputs:
  output_pdb_path:
    label: Path to the output file
    doc: |-
      Path to the output file
    type: File
    format: edam:format_1476 # pdb
    outputBinding:
      glob: $(inputs.output_pdb_path)

$namespaces:
  edam: https://edamontology.org/

$schemas:
- https://raw.githubusercontent.com/edamontology/edamontology/master/EDAM_dev.owl