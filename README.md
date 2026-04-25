# Tree-Sitter C Source Analyzer Demo

A Python demo program that uses [tree-sitter](https://tree-sitter.github.io/tree-sitter/)
to parse a C source file and display definitions, usages, and cross-references
of all tags/tokens found in the file.

## What it demonstrates

- Creating a tree-sitter **Parser** with the C language grammar
- **Parsing** C source code into an Abstract Syntax Tree (AST)
- **Walking** the AST to classify nodes as definitions or references
- Extracting **function**, **variable**, **struct**, **enum**, **typedef**,
  **macro**, and **parameter** definitions
- Building a **cross-reference table** linking each definition to its usage sites
- Displaying a compact **AST structure** view

## Requirements

- Python 3.10+
- Linux

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python tree_sitter_demo.py              # uses included sample.c
python tree_sitter_demo.py myfile.c     # analyse your own file
python tree_sitter_demo.py --ast-depth 5 sample.c  # deeper AST view
```

## Output sections

1. **Source listing** – the C file with line numbers
2. **AST structure** – compact tree view (configurable depth)
3. **Definitions** – all tags defined in the file (functions, variables, structs, …)
4. **Usages** – identifiers referencing a known definition, grouped by name
5. **Cross-reference** – each definition mapped to the lines where it is used

## Sample C file

`sample.c` is included and exercises: `#include`, `#define`, `typedef`,
`struct`, `enum`, function definitions, global/local variables, function calls,
and control flow.

## Logging

Debug-level logs are written to `/var/log/tree_sitter_demo.log` (falls back
to `~/tree_sitter_demo.log` if `/var/log` is not writable).
