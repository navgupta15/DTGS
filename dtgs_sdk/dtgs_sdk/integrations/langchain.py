"""
DTGS SDK — LangChain Integration.

Converts DTGS tools into LangChain ``StructuredTool`` instances that
automatically execute via the toolkit's direct HTTP executor.

Requires the ``langchain`` extra: ``pip install dtgs-sdk[langchain]``

Usage::

    from dtgs_sdk import DTGSToolkit
    from dtgs_sdk.integrations.langchain import create_dtgs_tools

    toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")
    tools = create_dtgs_tools(toolkit, query="refund payment")

    # Use with any LangChain agent
    from langchain.agents import create_react_agent
    agent = create_react_agent(llm, tools)
    result = agent.invoke({"input": "refund payment for order 5042"})
"""
from __future__ import annotations

import json
from typing import Any

from dtgs_sdk.toolkit import DTGSToolkit


def create_dtgs_tools(
    toolkit: DTGSToolkit,
    query: str | None = None,
) -> list:
    """
    Create LangChain StructuredTool instances from DTGS tools.

    Each tool automatically executes via the toolkit's HTTP executor,
    calling the backend API directly (DTGS is not involved in execution).

    Args:
        toolkit: An initialized DTGSToolkit instance.
        query: Optional query for filtering tools (used when namespace is large).

    Returns:
        List of LangChain ``StructuredTool`` instances.

    Raises:
        ImportError: If ``langchain-core`` is not installed.
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError:
        raise ImportError(
            "LangChain integration requires 'langchain-core'. "
            "Install with: pip install dtgs-sdk[langchain]"
        )

    tool_schemas = toolkit.get_tools(query=query)
    langchain_tools = []

    for schema in tool_schemas:
        func_def = schema.get("function", {})
        name = func_def.get("name", "unknown")
        description = func_def.get("description", "")
        parameters = func_def.get("parameters", {})

        # Build the argument schema for LangChain
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])

        # Create a closure that captures the tool name and toolkit
        def _make_executor(tool_name: str):
            def _execute(**kwargs: Any) -> str:
                result = toolkit.execute(tool_name, kwargs)
                return json.dumps(result, indent=2, default=str)
            return _execute

        # Build input schema dict for args_schema
        input_schema = _build_input_schema(name, properties, required)

        tool = StructuredTool(
            name=name,
            description=description,
            func=_make_executor(name),
            args_schema=input_schema,
        )
        langchain_tools.append(tool)

    return langchain_tools


def _build_input_schema(
    name: str,
    properties: dict,
    required: list[str],
) -> Any:
    """
    Build a Pydantic model from OpenAPI properties for LangChain's args_schema.
    """
    try:
        from pydantic import create_model, Field

        fields = {}
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        for prop_name, prop_schema in properties.items():
            python_type = type_map.get(prop_schema.get("type", "string"), str)
            description = prop_schema.get("description", "")
            default = ... if prop_name in required else None
            fields[prop_name] = (python_type, Field(default=default, description=description))

        model = create_model(f"{name}_Input", **fields)
        return model

    except Exception:
        # If Pydantic model creation fails, return None (LangChain will use dict)
        return None
