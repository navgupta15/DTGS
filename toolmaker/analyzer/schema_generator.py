"""
Schema Generator: converts AnalyzedMethod → OpenAI function-calling JSON schema.
"""
from __future__ import annotations

import re
from toolmaker.models import AnalyzedMethod, ToolSchema, ToolSchemaParameters

# Java type → JSON Schema type
_JAVA_TO_JSON: dict[str, str] = {
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
    "BigInteger": "integer",
    "float": "number",
    "Float": "number",
    "double": "number",
    "Double": "number",
    "BigDecimal": "number",
    "boolean": "boolean",
    "Boolean": "boolean",
    "void": "null",
    "Object": "object",
    "Map": "object",
    "HashMap": "object",
    "LinkedHashMap": "object",
    "TreeMap": "object",
    "List": "array",
    "ArrayList": "array",
    "LinkedList": "array",
    "Set": "array",
    "HashSet": "array",
    "TreeSet": "array",
    "Collection": "array",
    "Iterable": "array",
}


def _java_type_to_json_schema(java_type: str) -> str:
    """Map a Java type string to a JSON Schema type string."""
    # Strip generic parameters: List<String> → List
    base = re.sub(r"<[^>]+>", "", java_type).strip()
    # Strip array brackets: String[] → String
    base = base.rstrip("[]").strip()
    # Strip varargs
    base = base.rstrip(".").strip()
    return _JAVA_TO_JSON.get(base, "string")


def _sanitize_name(name: str) -> str:
    """Make a method name safe for use as an OpenAI function name."""
    # OpenAI function names: a-z, A-Z, 0-9, underscores, dashes. Max 64 chars.
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return safe[:64]


def method_to_tool_schema(method: AnalyzedMethod) -> ToolSchema:
    """
    Convert an AnalyzedMethod to an OpenAI function-calling ToolSchema.

    Args:
        method: The analyzed Java method.

    Returns:
        ToolSchema in OpenAI function-calling format.
    """
    # Build function name: ClassName_methodName
    func_name = _sanitize_name(f"{method.class_name}_{method.method_name}")

    # Description from Javadoc > REST annotation hint > fallback
    if method.javadoc:
        description = method.javadoc
    elif method.rest_annotations:
        description = f"REST endpoint ({method.rest_annotations[0]}): {method.qualified_name}"
    else:
        description = f"Java method: {method.qualified_name}"

    # Build parameters schema
    properties: dict[str, dict] = {}
    required: list[str] = []

    for param in method.parameters:
        json_type = _java_type_to_json_schema(param.java_type)
        prop: dict = {"type": json_type, "description": f"{param.java_type} {param.name}"}

        # If array type, add items schema
        if json_type == "array":
            prop["items"] = {"type": "string"}  # default, could be refined

        properties[param.name] = prop
        required.append(param.name)

    params = ToolSchemaParameters(
        type="object",
        properties=properties,
        required=required,
    )

    schema = ToolSchema.from_parts(
        name=func_name,
        description=description,
        parameters=params,
    )
    schema.function["__rest_annotations"] = method.rest_annotations
    return schema


def methods_to_tool_schemas(methods: list[AnalyzedMethod]) -> list[ToolSchema]:
    """Convert a list of AnalyzedMethod objects to ToolSchema list."""
    return [method_to_tool_schema(m) for m in methods]
