"""
Unit tests for the Schema Generator.
"""
import pytest
from toolmaker.models import AnalyzedMethod, JavaParameter
from toolmaker.analyzer.schema_generator import method_to_tool_schema


def _make_method(**kwargs) -> AnalyzedMethod:
    defaults = dict(
        source_file="Test.java",
        class_name="TestClass",
        method_name="testMethod",
        parameters=[],
        return_type="void",
        modifiers=["public"],
        javadoc=None,
        rest_annotations=[],
        line_number=1,
    )
    defaults.update(kwargs)
    return AnalyzedMethod(**defaults)


class TestSchemaStructure:
    def test_schema_type_is_function(self):
        m = _make_method()
        schema = method_to_tool_schema(m)
        assert schema.type == "function"

    def test_schema_has_function_dict(self):
        m = _make_method()
        schema = method_to_tool_schema(m)
        assert "name" in schema.function
        assert "description" in schema.function
        assert "parameters" in schema.function

    def test_function_name_includes_class_and_method(self):
        m = _make_method(class_name="OrderService", method_name="createOrder")
        schema = method_to_tool_schema(m)
        assert "OrderService" in schema.function["name"]
        assert "createOrder" in schema.function["name"]

    def test_parameters_type_is_object(self):
        m = _make_method()
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["type"] == "object"

    def test_empty_parameters_gives_empty_required(self):
        m = _make_method(parameters=[])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["required"] == []


class TestTypeMapping:
    def test_string_maps_to_string(self):
        m = _make_method(parameters=[JavaParameter(name="name", java_type="String")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["name"]["type"] == "string"

    def test_int_maps_to_integer(self):
        m = _make_method(parameters=[JavaParameter(name="count", java_type="int")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["count"]["type"] == "integer"

    def test_double_maps_to_number(self):
        m = _make_method(parameters=[JavaParameter(name="value", java_type="double")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["value"]["type"] == "number"

    def test_boolean_maps_to_boolean(self):
        m = _make_method(parameters=[JavaParameter(name="flag", java_type="boolean")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["flag"]["type"] == "boolean"

    def test_list_maps_to_array(self):
        m = _make_method(parameters=[JavaParameter(name="items", java_type="List<String>")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["items"]["type"] == "array"

    def test_unknown_type_maps_to_string(self):
        m = _make_method(parameters=[JavaParameter(name="obj", java_type="SomeCustomClass")])
        schema = method_to_tool_schema(m)
        assert schema.function["parameters"]["properties"]["obj"]["type"] == "object"


class TestDescriptionPriority:
    def test_javadoc_used_as_description(self):
        m = _make_method(javadoc="Returns the order by ID.")
        schema = method_to_tool_schema(m)
        assert schema.function["description"] == "Returns the order by ID."

    def test_rest_annotation_used_when_no_javadoc(self):
        m = _make_method(rest_annotations=["GetMapping"], javadoc=None)
        schema = method_to_tool_schema(m)
        assert "GetMapping" in schema.function["description"]

    def test_fallback_description_includes_qualified_name(self):
        m = _make_method(class_name="Foo", method_name="bar", javadoc=None, rest_annotations=[])
        schema = method_to_tool_schema(m)
        assert "Foo" in schema.function["description"]
        assert "bar" in schema.function["description"]

    def test_required_list_matches_parameter_names(self):
        m = _make_method(parameters=[
            JavaParameter(name="a", java_type="int"),
            JavaParameter(name="b", java_type="String"),
        ])
        schema = method_to_tool_schema(m)
        assert set(schema.function["parameters"]["required"]) == {"a", "b"}
