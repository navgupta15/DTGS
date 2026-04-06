"""
Unit tests for the Java AST Analyzer.
"""
from pathlib import Path
import pytest

from toolmaker.analyzer.java_analyzer import analyze_file

FIXTURE = Path(__file__).parent / "fixtures" / "SampleController.java"


@pytest.fixture(scope="module")
def methods():
    methods, _ = analyze_file(FIXTURE)
    return methods


def _get(methods, name):
    return next((m for m in methods if m.method_name == name), None)


class TestMethodExtraction:
    def test_finds_expected_method_count(self, methods):
        method_names = [m.method_name for m in methods]
        assert "greet" in method_names
        assert "add" in method_names
        assert "isPositive" in method_names
        assert "search" in method_names
        assert "createResource" in method_names
        assert "internalHelper" in method_names
        assert "factorial" in method_names

    def test_correct_class_name(self, methods):
        for m in methods:
            assert m.class_name == "SampleController"

    def test_greet_parameters(self, methods):
        m = _get(methods, "greet")
        assert m is not None
        assert len(m.parameters) == 1
        assert m.parameters[0].name == "name"
        assert m.parameters[0].java_type == "String"

    def test_add_parameters(self, methods):
        m = _get(methods, "add")
        assert m is not None
        assert len(m.parameters) == 2
        types = [p.java_type for p in m.parameters]
        assert "int" in types

    def test_add_return_type(self, methods):
        m = _get(methods, "add")
        assert m is not None
        assert "int" in m.return_type

    def test_search_generic_return_type(self, methods):
        m = _get(methods, "search")
        assert m is not None
        assert "List" in m.return_type

    def test_search_parameters(self, methods):
        m = _get(methods, "search")
        assert m is not None
        assert len(m.parameters) == 2
        names = {p.name for p in m.parameters}
        assert "query" in names
        assert "limit" in names

    def test_is_positive_boolean_param(self, methods):
        m = _get(methods, "isPositive")
        assert m is not None
        assert m.parameters[0].java_type == "double"

    def test_factorial_is_static(self, methods):
        m = _get(methods, "factorial")
        assert m is not None
        assert "static" in m.modifiers

    def test_internal_helper_is_private(self, methods):
        m = _get(methods, "internalHelper")
        assert m is not None
        assert "private" in m.modifiers

    def test_greet_is_public(self, methods):
        m = _get(methods, "greet")
        assert m is not None
        assert m.is_public is True


class TestJavadocExtraction:
    def test_greet_has_javadoc(self, methods):
        m = _get(methods, "greet")
        assert m is not None
        assert m.javadoc is not None
        assert "greeting" in m.javadoc.lower() or "name" in m.javadoc.lower()

    def test_add_has_javadoc(self, methods):
        m = _get(methods, "add")
        assert m is not None
        assert m.javadoc is not None
        assert "integer" in m.javadoc.lower() or "sum" in m.javadoc.lower()

    def test_internal_helper_no_javadoc(self, methods):
        m = _get(methods, "internalHelper")
        assert m is not None
        assert m.javadoc is None


class TestRestAnnotations:
    def test_greet_has_get_mapping(self, methods):
        m = _get(methods, "greet")
        assert m is not None
        assert any("GetMapping" in ann for ann in m.rest_annotations)
        assert m.is_rest_endpoint is True

    def test_create_resource_has_post_mapping(self, methods):
        m = _get(methods, "createResource")
        assert m is not None
        assert any("PostMapping" in ann for ann in m.rest_annotations)

    def test_add_has_no_rest_annotation(self, methods):
        m = _get(methods, "add")
        assert m is not None
        assert len(m.rest_annotations) == 0
        assert m.is_rest_endpoint is False

    def test_search_has_get_mapping(self, methods):
        m = _get(methods, "search")
        assert m is not None
        assert any("GetMapping" in ann for ann in m.rest_annotations)
