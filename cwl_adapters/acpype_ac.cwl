#!/usr/bin/env cwl-runner
cwlVersion: v1.0

class: CommandLineTool

label: This class is a wrapper of Acpype tool for small molecule parameterization
  for AMBER MD package.

doc: |-
  Generation of topologies for Antechamber. Acpype is a tool based in Python to use Antechamber to generate topologies for chemical compounds and to interface with others python applications like CCPN or ARIA. Visit the official page.

baseCommand: acpype_params_ac
arguments: ["--config", '{"basename": "$(inputs.base_name)", "charge": $(inputs.net_charge)}']

hints:
  DockerRequirement:
    dockerPull: quay.io/biocontainers/biobb_chemistry:3.7.0--pyhdfd78af_0

inputs:
  input_path:
    label: Path to the input file
    doc: |-
      Path to the input file
      Type: string
      File type: input
      Accepted formats: pdb, mdl, mol2
      Example file: https://github.com/bioexcel/biobb_chemistry/raw/master/biobb_chemistry/test/data/acpype/acpype.params.mol2
    type: File
    format:
    - edam:format_1476
    - edam:format_3815
    - edam:format_3816
    inputBinding:
      position: 1
      prefix: --input_path

  output_path_frcmod:
    label: Path to the FRCMOD output file
    doc: |-
      Path to the FRCMOD output file
      Type: string
      File type: output
      Accepted formats: frcmod
      Example file: https://github.com/bioexcel/biobb_chemistry/raw/master/biobb_chemistry/test/reference/acpype/ref_acpype.ac.frcmod
    type: string
    format:
    - edam:format_3888
    inputBinding:
      position: 2
      prefix: --output_path_frcmod
    default: system.frcmod

  output_path_inpcrd:
    label: Path to the INPCRD output file
    doc: |-
      Path to the INPCRD output file
      Type: string
      File type: output
      Accepted formats: inpcrd
      Example file: https://github.com/bioexcel/biobb_chemistry/raw/master/biobb_chemistry/test/reference/acpype/ref_acpype.ac.inpcrd
    type: string
    format:
    - edam:format_3878
    inputBinding:
      position: 3
      prefix: --output_path_inpcrd
    default: system.inpcrd

  output_path_lib:
    label: Path to the LIB output file
    doc: |-
      Path to the LIB output file
      Type: string
      File type: output
      Accepted formats: lib
      Example file: https://github.com/bioexcel/biobb_chemistry/raw/master/biobb_chemistry/test/reference/acpype/ref_acpype.ac.lib
    type: string
    format:
    - edam:format_3889
    inputBinding:
      position: 4
      prefix: --output_path_lib
    default: system.lib

  output_path_prmtop:
    label: Path to the PRMTOP output file
    doc: |-
      Path to the PRMTOP output file
      Type: string
      File type: output
      Accepted formats: prmtop
      Example file: https://github.com/bioexcel/biobb_chemistry/raw/master/biobb_chemistry/test/reference/acpype/ref_acpype.ac.prmtop
    type: string
    format:
    - edam:format_3881
    inputBinding:
      position: 5
      prefix: --output_path_prmtop
    default: system.prmtop

  base_name:
    label: Prefix for the output filenames
    doc: |-
      Prefix for the output filenames
      Type: string
    type: string
    format:
    - edam:format_2330
    default: ligand

  net_charge:
    label: net molecular charge (int), for gas default is 0
    doc: |-
      net molecular charge (int), for gas default is 0
      Type: int
    type: int?
    format:
    - edam:format_2330
    default: 0


outputs:
  output_path_frcmod:
    label: Path to the FRCMOD output file
    doc: |-
      Path to the FRCMOD output file
    type: File
    outputBinding:
      glob: $(inputs.output_path_frcmod)
    format: edam:format_3888

  output_path_inpcrd:
    label: Path to the INPCRD output file
    doc: |-
      Path to the INPCRD output file
    type: File
    outputBinding:
      glob: $(inputs.output_path_inpcrd)
    format: edam:format_3878

  output_path_lib:
    label: Path to the LIB output file
    doc: |-
      Path to the LIB output file
    type: File
    outputBinding:
      glob: $(inputs.output_path_lib)
    format: edam:format_3889

  output_path_prmtop:
    label: Path to the PRMTOP output file
    doc: |-
      Path to the PRMTOP output file
    type: File
    outputBinding:
      glob: $(inputs.output_path_prmtop)
    format: edam:format_3881

$namespaces:
  edam: https://edamontology.org/

$schemas:
- https://raw.githubusercontent.com/edamontology/edamontology/master/EDAM_dev.owl






