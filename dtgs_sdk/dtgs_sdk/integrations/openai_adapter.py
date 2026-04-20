"""
DTGS SDK — OpenAI Integration.

Helper functions for using DTGS tools with the OpenAI Python SDK directly.

Usage::

    from dtgs_sdk import DTGSToolkit
    from dtgs_sdk.integrations.openai_adapter import get_tools, handle_tool_calls

    toolkit = DTGSToolkit("http://dtgs:8000", namespace="order-service")

    # Get filtered tools for OpenAI API
    tools = get_tools(toolkit, query="refund payment")

    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=tools,
    )

    # Execute tool calls and get results
    tool_messages = handle_tool_calls(toolkit, response)
"""
from __future__ import annotations

import json
from typing import Any

from dtgs_sdk.toolkit import DTGSToolkit


def get_tools(toolkit: DTGSToolkit, query: str | None = None) -> list[dict]:
    """
    Get tools in OpenAI function-calling format with auto-filtering.

    This is a convenience wrapper around ``toolkit.get_tools()`` — the
    returned format is already OpenAI-compatible.

    Args:
        toolkit: An initialized DTGSToolkit instance.
        query: Optional query for filtering (used when namespace is large).

    Returns:
        List of tool dicts in OpenAI format.
    """
    return toolkit.get_tools(query=query)


def handle_tool_calls(
    toolkit: DTGSToolkit,
    response: Any,
) -> list[dict]:
    """
    Execute tool calls from an OpenAI chat completion response.

    Processes each tool call in the response, executes it via the toolkit's
    direct HTTP executor, and returns formatted tool messages for the next
    OpenAI API call.

    Args:
        toolkit: An initialized DTGSToolkit instance.
        response: The OpenAI ``ChatCompletion`` response object.

    Returns:
        List of tool message dicts ready to append to the messages list::

            [
                {
                    "role": "tool",
                    "tool_call_id": "call_abc123",
                    "content": '{"status_code": 200, "body": {...}}'
                }
            ]

    Example::

        response = openai.chat.completions.create(...)
        if response.choices[0].message.tool_calls:
            tool_messages = handle_tool_calls(toolkit, response)
            messages.append(response.choices[0].message)
            messages.extend(tool_messages)
            # Make another API call with tool results
            final = openai.chat.completions.create(messages=messages, ...)
    """
    message = response.choices[0].message
    if not message.tool_calls:
        return []

    tool_messages = []
    for tc in message.tool_calls:
        tool_name = tc.function.name
        try:
            tool_args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            tool_args = {}

        # Execute directly against backend
        result = toolkit.execute(tool_name, tool_args)

        tool_messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result, indent=2, default=str),
        })

    return tool_messages


def execute_tool_call(
    toolkit: DTGSToolkit,
    tool_name: str,
    arguments: str | dict,
) -> dict:
    """
    Execute a single tool call.

    Args:
        toolkit: An initialized DTGSToolkit instance.
        tool_name: The function/tool name.
        arguments: Arguments as a JSON string or dict.

    Returns:
        Execution result dict from the backend.
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}

    return toolkit.execute(tool_name, arguments)
