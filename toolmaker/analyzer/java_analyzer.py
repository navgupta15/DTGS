"""
Java AST Analyzer using tree-sitter-java.

Parses .java source files and extracts:
- Class names
- Method names, parameters (type + name), return types, modifiers
- Javadoc comments preceding method declarations
- Spring Boot REST annotations (@GetMapping, @PostMapping, etc.)
"""
from __future__ import annotations

import re
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

from toolmaker.models import AnalyzedMethod, JavaParameter

# ── Language & Parser (module-level singleton) ─────────────────────────────
JAVA_LANGUAGE = Language(tsjava.language())
_parser = Parser(JAVA_LANGUAGE)

# ── REST annotation set ────────────────────────────────────────────────────
REST_ANNOTATIONS = {
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "DeleteMapping",
    "PatchMapping",
    "RequestMapping",
}

# ── Type mapping: Java primitive/common → JSON Schema type ─────────────────
JAVA_TYPE_MAP: dict[str, str] = {
    "String": "string",
    "string": "string",
    "char": "string",
    "Character": "string",
    "int": "integer",
    "Integer": "integer",
    "long": "integer",
    "Long": "integer",
    "short": "integer",
    "Short": "integer",
    "byte": "integer",
    "Byte": "integer",
    "float": "number",
    "Float": "number",
    "double": "number",
    "Double": "number",
    "boolean": "boolean",
    "Boolean": "boolean",
    "void": "null",
    "Object": "object",
    "Map": "object",
    "HashMap": "object",
    "LinkedHashMap": "object",
    "List": "array",
    "ArrayList": "array",
    "Set": "array",
    "HashSet": "array",
    "Collection": "array",
}


def _node_text(node: Node, source: bytes) -> str:
    """Extract raw text of a node from the source bytes."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _strip_generic(java_type: str) -> str:
    """Remove generic parameters: List<String> → List"""
    return re.sub(r"<[^>]+>", "", java_type).strip()


def _extract_javadoc(node: Node, source: bytes) -> str | None:
    """
    Look for a block_comment immediately before this node in the
    parent's children that starts with '/**'.
    """
    parent = node.parent
    if parent is None:
        return None

    target_start = node.start_point[0]
    prev_comment: str | None = None

    for child in parent.children:
        if child.end_point[0] < target_start:
            if child.type == "block_comment":
                text = _node_text(child, source)
                if text.startswith("/**"):
                    prev_comment = text
                else:
                    prev_comment = None  # reset on non-javadoc block comment
            elif child.type == "line_comment":
                # A // comment between the Javadoc and the method breaks association
                prev_comment = None
        elif child.id == node.id:
            break

    if prev_comment is None:
        return None

    # Clean up Javadoc: strip /** ... */ and leading * on each line
    lines = prev_comment.strip().removeprefix("/**").removesuffix("*/").strip().splitlines()
    cleaned = []
    for line in lines:
        line = line.strip().lstrip("*").strip()
        if line:
            cleaned.append(line)
    return " ".join(cleaned) if cleaned else None


def _extract_annotations(node: Node, source: bytes) -> list[str]:
    """
    Extract annotation names from a modifiers node or class/method body.
    Looks at preceding siblings for annotation nodes.
    """
    annotations: list[str] = []
    parent = node.parent
    if parent is None:
        return annotations

    for child in parent.children:
        if child.id == node.id:
            break
        if child.type in ("marker_annotation", "annotation"):
            # annotation name is typically the first named child
            for subchild in child.children:
                if subchild.type == "identifier":
                    annotations.append(_node_text(subchild, source))
                    break

    return annotations


def _parse_formal_parameters(params_node: Node, source: bytes) -> list[JavaParameter]:
    """Parse a formal_parameters node into a list of JavaParameter."""
    parameters: list[JavaParameter] = []
    for child in params_node.children:
        if child.type in ("formal_parameter", "receiver_parameter"):
            param_type: str = ""
            param_name: str = ""
            param_annotations: list[str] = []

            for sub in child.children:
                if sub.type in (
                    "type_identifier",
                    "integral_type",
                    "floating_point_type",
                    "boolean_type",
                    "void_type",
                    "generic_type",
                    "array_type",
                ):
                    param_type = _node_text(sub, source)
                elif sub.type == "identifier":
                    param_name = _node_text(sub, source)
                elif sub.type in ("marker_annotation", "annotation"):
                    for subchild in sub.children:
                        if subchild.type == "identifier":
                            param_annotations.append(_node_text(subchild, source))
                            break

            if param_name and param_type:
                parameters.append(
                    JavaParameter(
                        name=param_name,
                        java_type=param_type,
                        annotations=param_annotations,
                    )
                )
        elif child.type == "spread_parameter":
            # varargs: e.g. String... args
            param_type = ""
            param_name = ""
            for sub in child.children:
                if sub.type in (
                    "type_identifier",
                    "generic_type",
                    "integral_type",
                    "array_type",
                ):
                    param_type = _node_text(sub, source) + "..."
                elif sub.type == "identifier":
                    param_name = _node_text(sub, source)
            if param_name:
                parameters.append(
                    JavaParameter(name=param_name, java_type=param_type or "Object...")
                )

    return parameters


def _extract_methods_from_class(
    class_node: Node,
    class_name: str,
    source: bytes,
    source_file: str,
) -> list[AnalyzedMethod]:
    """Walk a class body and extract all method declarations."""
    methods: list[AnalyzedMethod] = []

    # Find class_body
    class_body: Node | None = None
    for child in class_node.children:
        if child.type == "class_body":
            class_body = child
            break

    if class_body is None:
        return methods

    for child in class_body.children:
        if child.type != "method_declaration":
            continue

        method_name = ""
        return_type = "void"
        modifiers: list[str] = []
        parameters: list[JavaParameter] = []
        rest_annotations: list[str] = []

        # Walk method_declaration children
        for sub in child.children:
            if sub.type == "modifiers":
                for mod in sub.children:
                    text = _node_text(mod, source)
                    if mod.type in (
                        "public",
                        "private",
                        "protected",
                        "static",
                        "final",
                        "abstract",
                        "synchronized",
                        "native",
                        "transient",
                        "volatile",
                        "strictfp",
                        "default",
                    ):
                        modifiers.append(text)
                    elif mod.type in ("marker_annotation", "annotation"):
                        ann_name = ""
                        for ann_child in mod.children:
                            if ann_child.type == "identifier":
                                ann_name = _node_text(ann_child, source)
                                break
                        if ann_name in REST_ANNOTATIONS:
                            rest_annotations.append(ann_name)

            elif sub.type in (
                "type_identifier",
                "void_type",
                "integral_type",
                "floating_point_type",
                "boolean_type",
                "generic_type",
                "array_type",
            ):
                return_type = _node_text(sub, source)

            elif sub.type == "identifier":
                method_name = _node_text(sub, source)

            elif sub.type == "formal_parameters":
                parameters = _parse_formal_parameters(sub, source)

        if not method_name:
            continue

        javadoc = _extract_javadoc(child, source)

        methods.append(
            AnalyzedMethod(
                source_file=source_file,
                class_name=class_name,
                method_name=method_name,
                parameters=parameters,
                return_type=return_type,
                modifiers=modifiers,
                javadoc=javadoc,
                rest_annotations=rest_annotations,
                line_number=child.start_point[0] + 1,
            )
        )

    return methods


def _find_class_name(node: Node, source: bytes) -> str:
    """Extract the simple class name from a class_declaration node."""
    for child in node.children:
        if child.type == "identifier":
            return _node_text(child, source)
    return "Unknown"


def analyze_file(path: Path) -> list[AnalyzedMethod]:
    """
    Parse a single .java file and return all extracted methods.

    Args:
        path: Absolute path to a .java source file.

    Returns:
        List of AnalyzedMethod instances, one per method declaration found.
    """
    source = path.read_bytes()
    tree = _parser.parse(source)
    root = tree.root_node
    source_file = str(path)

    methods: list[AnalyzedMethod] = []

    def walk(node: Node, enclosing_class: str = "") -> None:
        if node.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            class_name = _find_class_name(node, source)
            if node.type == "class_declaration":
                new_methods = _extract_methods_from_class(
                    node, class_name, source, source_file
                )
                methods.extend(new_methods)
            # Recurse for nested classes
            for child in node.children:
                walk(child, class_name)
        else:
            for child in node.children:
                walk(child, enclosing_class)

    walk(root)
    return methods


def analyze_directory(root: Path) -> list[AnalyzedMethod]:
    """
    Analyze all .java files under a directory.

    Args:
        root: Root directory to search.

    Returns:
        Flat list of all AnalyzedMethod instances across all files.
    """
    from toolmaker.ingestion.github import find_java_files

    all_methods: list[AnalyzedMethod] = []
    java_files = find_java_files(root)

    for java_file in java_files:
        try:
            file_methods = analyze_file(java_file)
            all_methods.extend(file_methods)
        except Exception as exc:
            # Log and continue — one bad file shouldn't stop the whole analysis
            import warnings
            warnings.warn(f"Failed to parse {java_file}: {exc}", stacklevel=2)

    return all_methods
