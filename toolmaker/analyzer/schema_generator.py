"""
Schema Generator: converts AnalyzedMethod → OpenAI function-calling JSON schema.
"""
from __future__ import annotations

import re
from toolmaker.models import AnalyzedMethod, ToolSchema, ToolSchemaParameters, AnalyzedClass

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


def _build_properties_recursively(
    java_type: str, 
    classes_registry: dict[str, AnalyzedClass],
    visited: set[str]
) -> dict:
    """Builds a JSON schema dictionary for a given java type, expanding objects."""
    # Extract inner type for generics (e.g., List<Pet> -> Pet)
    match = re.search(r"^[A-Za-z0-9_]+\s*<\s*([^>]+)\s*>", java_type)
    inner_type = match.group(1).strip() if match else ""
    
    base_type = re.sub(r"<[^>]+>", "", java_type).strip().rstrip("[]").rstrip(".").strip()
    
    json_type = _JAVA_TO_JSON.get(base_type)
    is_array = "[]" in java_type or json_type == "array"
    
    if is_array:
        # If it's an array/list, recursively build the schema for its items!
        item_schema = _build_properties_recursively(inner_type, classes_registry, visited) if inner_type else {"type": "string"}
        return {"type": "array", "items": item_schema}
        
    if json_type and json_type != "object":
        return {"type": json_type}
        
    if base_type in visited:
        return {"type": "object", "description": "Recursive reference"}
        
    # Attempt to find the base type either directly or by its simple name (if fully qualified)
    registry_key = base_type if base_type in classes_registry else base_type.split('.')[-1]
        
    if registry_key in classes_registry:
        visited.add(registry_key)
        obj_props = {}
        required = []
        for field in classes_registry[registry_key].fields:
            field_schema = _build_properties_recursively(field.java_type, classes_registry, visited)
            field_schema["description"] = f"{field.name} ({field.java_type})"
            obj_props[field.name] = field_schema
            required.append(field.name)
        visited.remove(registry_key)
        
        schema: dict = {"type": "object", "properties": obj_props}
        if required:
            schema["required"] = required
            
        return schema
        
    # Unmapped or external class object fallback
    return {"type": "object"}


def method_to_tool_schema(
    method: AnalyzedMethod,
    classes_registry: dict[str, AnalyzedClass] | None = None
) -> ToolSchema:
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

    classes_registry = classes_registry or {}

    for param in method.parameters:
        prop = _build_properties_recursively(param.java_type, classes_registry, set())
        prop["description"] = f"{param.java_type} {param.name}"

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
    schema.function["__class_rest_annotations"] = method.class_rest_annotations
    return schema


def methods_to_tool_schemas(
    methods: list[AnalyzedMethod],
    classes_registry: dict[str, AnalyzedClass] | None = None
) -> list[ToolSchema]:
    """Convert a list of AnalyzedMethod objects to ToolSchema list."""
    return [method_to_tool_schema(m, classes_registry) for m in methods]
