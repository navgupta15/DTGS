"""
Pydantic models for the Java Analysis Engine.
"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class JavaParameter(BaseModel):
    """Represents a single parameter of a Java method."""
    name: str
    java_type: str
    annotations: list[str] = Field(default_factory=list)


class AnalyzedMethod(BaseModel):
    """
    Represents a single extracted Java method with all metadata
    needed to generate an LLM tool schema.
    """
    source_file: str
    class_name: str
    method_name: str
    parameters: list[JavaParameter] = Field(default_factory=list)
    return_type: str = "void"
    modifiers: list[str] = Field(default_factory=list)
    javadoc: str | None = None
    rest_annotations: list[str] = Field(default_factory=list)
    class_rest_annotations: list[str] = Field(default_factory=list)
    line_number: int = 0

    @property
    def is_public(self) -> bool:
        return "public" in self.modifiers

    @property
    def is_rest_endpoint(self) -> bool:
        return len(self.rest_annotations) > 0

    @property
    def qualified_name(self) -> str:
        return f"{self.class_name}.{self.method_name}"


class ToolSchemaProperty(BaseModel):
    """JSON Schema property for a single parameter."""
    type: str
    description: str = ""


class ToolSchemaParameters(BaseModel):
    """JSON Schema object for function parameters."""
    type: str = "object"
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolSchema(BaseModel):
    """
    OpenAI function-calling compatible tool schema.
    See: https://platform.openai.com/docs/api-reference/chat/create#chat-create-tools
    """
    type: str = "function"
    function: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_parts(
        cls,
        name: str,
        description: str,
        parameters: ToolSchemaParameters,
    ) -> "ToolSchema":
        return cls(
            function={
                "name": name,
                "description": description,
                "parameters": parameters.model_dump(),
            }
        )
