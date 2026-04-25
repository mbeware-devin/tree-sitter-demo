#!/usr/bin/env python3
"""
tree_sitter_demo.py - Demonstrate tree-sitter by parsing a C source file.

Reads a C file, builds an AST with tree-sitter, then extracts and displays:
  1. The source code with line numbers
  2. All tag definitions (functions, variables, structs, enums, typedefs, macros)
  3. All tag usages / references
  4. A cross-reference table linking definitions to their usage sites
"""

import argparse
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_c as tsc
from tree_sitter import Language, Parser

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def _pick_log_dir():
    """Use /var/log if writable, otherwise fall back to $HOME."""
    var_log = Path("/var/log")
    if var_log.is_dir():
        try:
            test_file = var_log / ".tree_sitter_demo_probe"
            test_file.touch()
            test_file.unlink()
            return var_log
        except OSError:
            pass
    return Path.home()

LOG_DIR = _pick_log_dir()
LOG_FILE = LOG_DIR / "tree_sitter_demo.log"

logger = logging.getLogger("tree_sitter_demo")
logger.setLevel(logging.DEBUG)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)

_console_handler = logging.StreamHandler(sys.stderr)
_console_handler.setLevel(logging.WARNING)
_console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

# ---------------------------------------------------------------------------
# ANSI helpers (Linux only)
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class TagInfo:
    """A single definition or usage of a tag (identifier) in the source."""
    name: str
    kind: str          # e.g. "function", "variable", "struct", "enum", "typedef", "macro"
    line: int          # 1-based
    column: int        # 0-based
    is_definition: bool

@dataclass
class CrossRef:
    """Aggregated cross-reference for one tag name."""
    name: str
    kind: str
    def_lines: list[int] = field(default_factory=list)
    use_lines: list[int] = field(default_factory=list)

# ---------------------------------------------------------------------------
# AST node type sets used for classification
# ---------------------------------------------------------------------------
# Node types that represent *definitions*
DEFINITION_NODE_TYPES = {
    "function_definition",
    "declaration",
    "struct_specifier",
    "enum_specifier",
    "union_specifier",
    "type_definition",
    "preproc_def",
    "preproc_function_def",
}

# ---------------------------------------------------------------------------
# Tree walking
# ---------------------------------------------------------------------------
def walk_tree(node, callback):
    """Depth-first walk of the tree, calling callback(node) on every node."""
    callback(node)
    for child in node.children:
        walk_tree(child, callback)


def extract_tags(root_node, source_bytes):
    """
    Walk the AST and return two lists: (definitions, usages).

    Strategy:
      - For each interesting node type, figure out the identifier name and
        whether it is a definition or a usage.
      - We track definition names so that later identifier references can be
        classified as usages.
    """
    definitions: list[TagInfo] = []
    usages: list[TagInfo] = []
    defined_names: dict[str, str] = {}  # name -> kind

    # --- Pass 1: collect definitions ---
    def collect_definitions(node):
        tag = _try_extract_definition(node, source_bytes)
        if tag is not None:
            definitions.append(tag)
            defined_names[tag.name] = tag.kind
            logger.debug("DEF  %-12s %-20s line %d", tag.kind, tag.name, tag.line)

    walk_tree(root_node, collect_definitions)

    # --- Pass 2: collect usages (identifiers that reference a known definition) ---
    def collect_usages(node):
        if node.type not in ("identifier", "type_identifier"):
            return
        name = node.text.decode("utf-8")
        if name not in defined_names:
            return
        # Skip if this very node is already part of a definition site
        if _is_definition_site(node):
            return
        kind = defined_names[name]
        tag = TagInfo(
            name=name,
            kind=kind,
            line=node.start_point[0] + 1,
            column=node.start_point[1],
            is_definition=False,
        )
        usages.append(tag)
        logger.debug("USE  %-12s %-20s line %d", tag.kind, tag.name, tag.line)

    walk_tree(root_node, collect_usages)

    return definitions, usages


# ---------------------------------------------------------------------------
# Definition extraction helpers
# ---------------------------------------------------------------------------
def _try_extract_definition(node, source_bytes):
    """Return a TagInfo if *node* is a definition we care about, else None."""

    # --- Preprocessor macro: #define FOO ... ---
    if node.type in ("preproc_def", "preproc_function_def"):
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return _make_tag(name_node, "macro", is_def=True)

    # --- Function definition ---
    if node.type == "function_definition":
        declarator = node.child_by_field_name("declarator")
        name_node = _find_identifier(declarator)
        if name_node is not None:
            return _make_tag(name_node, "function", is_def=True)

    # --- Type definition (typedef) ---
    if node.type == "type_definition":
        declarator = node.child_by_field_name("declarator")
        name_node = _find_identifier(declarator)
        if name_node is not None:
            return _make_tag(name_node, "typedef", is_def=True)

    # --- Struct / enum / union with a tag name ---
    if node.type in ("struct_specifier", "enum_specifier", "union_specifier"):
        name_node = node.child_by_field_name("name")
        if name_node is not None and node.child_by_field_name("body") is not None:
            kind = node.type.replace("_specifier", "")
            return _make_tag(name_node, kind, is_def=True)

    # --- Enum enumerator (individual constant inside an enum body) ---
    if node.type == "enumerator":
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return _make_tag(name_node, "enum_constant", is_def=True)

    # --- Variable / parameter declaration ---
    if node.type == "declaration":
        # A declaration can declare multiple variables. We pick up each declarator.
        tags = _extract_declaration_names(node)
        # Return the first one; the rest are appended by the caller via walk_tree.
        # Actually, we handle it differently: we'll return None here and handle
        # declarations separately.
        pass

    if node.type == "init_declarator":
        declarator = node.child_by_field_name("declarator")
        name_node = _find_identifier(declarator)
        if name_node is not None:
            storage = _storage_class(node)
            kind = f"variable ({storage})" if storage else "variable"
            return _make_tag(name_node, kind, is_def=True)

    # Plain declarator directly under a declaration (no initializer)
    if node.type == "declaration":
        for child in node.children:
            if child.type in ("identifier", "pointer_declarator", "array_declarator", "function_declarator"):
                name_node = _find_identifier(child)
                if name_node is not None:
                    # Distinguish function prototypes from plain variables
                    if _has_function_declarator(child):
                        kind = "function (prototype)"
                    else:
                        storage = _storage_class(node)
                        kind = f"variable ({storage})" if storage else "variable"
                    return _make_tag(name_node, kind, is_def=True)

    # --- Function parameter ---
    if node.type == "parameter_declaration":
        declarator = node.child_by_field_name("declarator")
        name_node = _find_identifier(declarator)
        if name_node is not None:
            return _make_tag(name_node, "parameter", is_def=True)

    return None


def _extract_declaration_names(node):
    """Extract all declared names from a declaration node (unused, kept for reference)."""
    names = []
    for child in node.children:
        if child.type in ("init_declarator", "identifier", "pointer_declarator", "array_declarator"):
            id_node = _find_identifier(child)
            if id_node is not None:
                names.append(id_node)
    return names


def _find_identifier(node):
    """Descend into declarator wrappers to find the actual identifier node."""
    if node is None:
        return None
    if node.type in ("identifier", "type_identifier"):
        return node
    if node.type in (
        "pointer_declarator",
        "array_declarator",
        "function_declarator",
        "parenthesized_declarator",
    ):
        # These wrappers have the actual declarator as a child
        declarator = node.child_by_field_name("declarator")
        if declarator is not None:
            return _find_identifier(declarator)
        # Fallback: search children
        for child in node.children:
            result = _find_identifier(child)
            if result is not None:
                return result
    return None


def _has_function_declarator(node):
    """Return True if node is or contains a function_declarator."""
    if node is None:
        return False
    if node.type == "function_declarator":
        return True
    for child in node.children:
        if _has_function_declarator(child):
            return True
    return False


def _is_definition_site(node):
    """Heuristic: return True if this identifier node is at a definition site.

    A type_identifier used as a type specifier (return type, field type, cast)
    is a *usage* of that type, not a definition — so we return False for those.
    """
    # type_identifier used as a type reference is always a usage, unless it is
    # the declarator of a type_definition (the name being defined).
    if node.type == "type_identifier":
        parent = node.parent
        if parent is None:
            return False
        # The only time a type_identifier is a definition is when it is the
        # declarator child of a type_definition node.
        if parent.type == "type_definition":
            field = parent.child_by_field_name("declarator")
            if field is not None and field.id == node.id:
                return True
        return False

    parent = node.parent
    if parent is None:
        return False
    if parent.type in DEFINITION_NODE_TYPES:
        return True
    if parent.type in (
        "init_declarator",
        "pointer_declarator",
        "array_declarator",
        "function_declarator",
        "type_definition",
        "enumerator",
        "preproc_def",
        "preproc_function_def",
        "parameter_declaration",
    ):
        return True
    # Declarator that lives inside a definition
    if parent.type in ("declaration", "function_definition"):
        return True
    return False


def _storage_class(node):
    """Return 'static', 'extern', etc. if present on the declaration, else ''."""
    decl = node
    while decl is not None and decl.type != "declaration":
        decl = decl.parent
    if decl is None:
        return ""
    for child in decl.children:
        if child.type == "storage_class_specifier":
            return child.text.decode("utf-8")
    return ""


def _make_tag(name_node, kind, is_def):
    return TagInfo(
        name=name_node.text.decode("utf-8"),
        kind=kind,
        line=name_node.start_point[0] + 1,
        column=name_node.start_point[1],
        is_definition=is_def,
    )


# ---------------------------------------------------------------------------
# Cross-reference builder
# ---------------------------------------------------------------------------
def build_crossref(definitions, usages):
    """Merge definitions and usages into a dict of CrossRef keyed by name."""
    refs: dict[str, CrossRef] = {}

    for d in definitions:
        if d.name not in refs:
            refs[d.name] = CrossRef(name=d.name, kind=d.kind)
        refs[d.name].def_lines.append(d.line)

    for u in usages:
        if u.name not in refs:
            refs[u.name] = CrossRef(name=u.name, kind=u.kind)
        refs[u.name].use_lines.append(u.line)

    return refs


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def print_source(source_text, filename):
    """Print the source file with line numbers."""
    lines = source_text.splitlines()
    width = len(str(len(lines)))
    print(f"\n{BOLD}{CYAN}{'=' * 70}")
    print(f" Source: {filename}")
    print(f"{'=' * 70}{RESET}\n")
    for i, line in enumerate(lines, start=1):
        print(f"  {DIM}{i:>{width}}{RESET}  {line}")
    print()


def print_definitions(definitions):
    """Print a table of all definitions."""
    print(f"{BOLD}{GREEN}{'=' * 70}")
    print(f" Definitions")
    print(f"{'=' * 70}{RESET}\n")
    if not definitions:
        print("  (none found)\n")
        return
    print(f"  {'Line':>5}  {'Kind':<20}  {'Name'}")
    print(f"  {'----':>5}  {'----':<20}  {'----'}")
    for d in sorted(definitions, key=lambda t: t.line):
        print(f"  {d.line:>5}  {d.kind:<20}  {d.name}")
    print()


def print_usages(usages):
    """Print usages grouped by tag name."""
    print(f"{BOLD}{YELLOW}{'=' * 70}")
    print(f" Usages / References")
    print(f"{'=' * 70}{RESET}\n")
    if not usages:
        print("  (none found)\n")
        return
    grouped = defaultdict(list)
    for u in usages:
        grouped[u.name].append(u.line)
    for name in sorted(grouped):
        lines_str = ", ".join(str(ln) for ln in sorted(set(grouped[name])))
        print(f"  {name:<25} lines: {lines_str}")
    print()


def print_crossref(refs):
    """Print the cross-reference table."""
    print(f"{BOLD}{MAGENTA}{'=' * 70}")
    print(f" Cross-Reference: Definition -> Usages")
    print(f"{'=' * 70}{RESET}\n")
    if not refs:
        print("  (none)\n")
        return
    for name in sorted(refs):
        cr = refs[name]
        def_str = ", ".join(str(ln) for ln in cr.def_lines) if cr.def_lines else "(none)"
        use_str = ", ".join(str(ln) for ln in sorted(set(cr.use_lines))) if cr.use_lines else "(none)"
        print(f"  {BOLD}{name}{RESET}  [{cr.kind}]")
        print(f"      defined at line(s): {def_str}")
        print(f"      used at line(s):    {use_str}")
        print()


def print_ast_excerpt(root_node, max_depth=3):
    """Print a compact view of the top-level AST structure."""
    print(f"{BOLD}{RED}{'=' * 70}")
    print(f" AST Structure (depth <= {max_depth})")
    print(f"{'=' * 70}{RESET}\n")
    _print_node(root_node, depth=0, max_depth=max_depth)
    print()


def _print_node(node, depth, max_depth):
    if depth > max_depth:
        return
    indent = "  " + "  " * depth
    loc = f"[{node.start_point[0]+1}:{node.start_point[1]}]"
    extra = ""
    if node.child_count == 0:
        text = node.text.decode("utf-8")
        if len(text) > 40:
            text = text[:37] + "..."
        extra = f'  "{text}"'
    print(f"{indent}{DIM}{loc:>10}{RESET}  {node.type}{extra}")
    for child in node.children:
        _print_node(child, depth + 1, max_depth)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Demonstrate tree-sitter by analysing a C source file.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="sample.c",
        help="Path to the C source file to analyse (default: sample.c)",
    )
    parser.add_argument(
        "--ast-depth",
        type=int,
        default=3,
        help="Max depth for AST structure display (default: 3)",
    )
    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.is_file():
        logger.error("File not found: %s", filepath)
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    source_bytes = filepath.read_bytes()
    source_text = source_bytes.decode("utf-8")

    logger.info("Parsing %s (%d bytes)", filepath, len(source_bytes))

    # --- Set up tree-sitter parser with C language ---
    c_language = Language(tsc.language())
    ts_parser = Parser(c_language)

    tree = ts_parser.parse(source_bytes)
    root = tree.root_node

    logger.info("AST root type: %s, children: %d", root.type, root.child_count)

    # --- Extract tags ---
    definitions, usages = extract_tags(root, source_bytes)
    refs = build_crossref(definitions, usages)

    logger.info("Found %d definitions, %d usages", len(definitions), len(usages))

    # --- Display everything ---
    print_source(source_text, filepath.name)
    print_ast_excerpt(root, max_depth=args.ast_depth)
    print_definitions(definitions)
    print_usages(usages)
    print_crossref(refs)

    print(f"{BOLD}Done. Log written to: {LOG_FILE}{RESET}")


if __name__ == "__main__":
    main()
