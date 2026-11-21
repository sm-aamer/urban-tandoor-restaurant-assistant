import asyncio
import json
from collections.abc import Mapping
from typing import cast

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from openai.types.chat import ChatCompletionMessageParam

from app.chat import tools
from app.chat.llm import build_openrouter_tools
from app.chat.state import ChatContext, ChatState

MAX_MODEL_ITERATIONS = 4
MAX_TOOL_CALLS = 6
MAX_TOOL_OUTPUT_CHARS = 12_000
MODEL_REQUEST_TIMEOUT_SECONDS = 30

LIMIT_MESSAGE = (
    "I couldn't complete that lookup within the allowed limits. "
    "Please try a narrower question."
)
LOOKUP_REQUIRED_MESSAGE = (
    "I need to check the restaurant records before answering. Please ask about "
    "branches, suppliers, ingredients, menu items, recipes, menu availability, "
    "or stock movement history."
)
UNAVAILABLE_TOOL_MESSAGE = (
    "I couldn't access that requested information. Please ask about branches, "
    "suppliers, ingredients, menu items, recipes, menu availability, or stock "
    "movement history."
)


async def _call_model(
    state: ChatState,
    runtime: Runtime[ChatContext],
) -> dict[str, object]:
    client = runtime.context["client"]
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=runtime.context["model"],
            messages=state["messages"],
            tools=build_openrouter_tools(),
            tool_choice="auto",
            temperature=0,
            max_tokens=1024,
        ),
        timeout=MODEL_REQUEST_TIMEOUT_SECONDS,
    )
    choices = response.choices
    if not choices:
        return {
            "answer": UNAVAILABLE_TOOL_MESSAGE,
            "iteration_count": state["iteration_count"] + 1,
            "pending_tool_calls": [],
            "stop_reason": "empty_provider_response",
        }

    model_message = choices[0].message
    tool_calls = model_message.tool_calls or []
    assistant_message: dict[str, object] = {
        "role": "assistant",
        "content": model_message.content,
    }
    if tool_calls:
        assistant_message["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in tool_calls
        ]
    messages = [
        *state["messages"],
        cast(ChatCompletionMessageParam, assistant_message),
    ]
    if tool_calls:
        return {
            "messages": messages,
            "iteration_count": state["iteration_count"] + 1,
            "pending_tool_calls": list(tool_calls),
        }

    answer = (model_message.content or "").strip()
    if not answer:
        answer = UNAVAILABLE_TOOL_MESSAGE
    elif state["retrieval_count"] == 0:
        answer = LOOKUP_REQUIRED_MESSAGE
    return {
        "answer": answer[:2_000],
        "messages": messages,
        "iteration_count": state["iteration_count"] + 1,
        "pending_tool_calls": [],
        "stop_reason": "completed",
    }


def _bounded_tool_result(result: dict[str, object]) -> dict[str, object]:
    serialized = json.dumps(result, ensure_ascii=True, separators=(",", ":"))
    if len(serialized) <= MAX_TOOL_OUTPUT_CHARS:
        return result
    return {
        "error": (
            "The retrieval result exceeded the response-size limit. "
            "Refine the question to request fewer records."
        )
    }


async def _execute_tools(
    state: ChatState,
    runtime: Runtime[ChatContext],
) -> dict[str, object]:
    function_calls = state["pending_tool_calls"]
    remaining = MAX_TOOL_CALLS - state["tool_call_count"]
    if (
        state["iteration_count"] >= MAX_MODEL_ITERATIONS
        or len(function_calls) > remaining
    ):
        return {
            "answer": LIMIT_MESSAGE,
            "pending_tool_calls": [],
            "stop_reason": "limit_reached",
        }

    if any(
        not function_call.id
        or function_call.function.name not in tools.APPROVED_TOOLS
        for function_call in function_calls
    ):
        return {
            "answer": UNAVAILABLE_TOOL_MESSAGE,
            "pending_tool_calls": [],
            "stop_reason": "unapproved_tool",
        }

    tool_messages: list[ChatCompletionMessageParam] = []
    session = runtime.context["session"]
    retrieval_count = state["retrieval_count"]
    for function_call in function_calls:
        name = function_call.function.name
        try:
            raw_arguments = json.loads(function_call.function.arguments)
            if not isinstance(raw_arguments, Mapping):
                raise TypeError
            arguments: Mapping[str, object] = raw_arguments
        except (TypeError, ValueError):
            result = {"error": "The retrieval request was invalid."}
        else:
            try:
                result = await tools.execute_tool(session, name, arguments)
            except tools.ChatToolError:
                result = {"error": "The retrieval request was invalid."}
        bounded_result = _bounded_tool_result(result)
        if "error" not in bounded_result:
            retrieval_count += 1
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": function_call.id,
                "content": json.dumps(
                    bounded_result,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            }
        )

    return {
        "messages": [*state["messages"], *tool_messages],
        "tool_call_count": state["tool_call_count"] + len(function_calls),
        "retrieval_count": retrieval_count,
        "pending_tool_calls": [],
    }


def _route_after_model(state: ChatState) -> str:
    if state["answer"] or state["stop_reason"] is not None:
        return END
    if state["iteration_count"] >= MAX_MODEL_ITERATIONS:
        return "limit"
    if state["pending_tool_calls"]:
        return "tools"
    return END


def _route_after_tools(state: ChatState) -> str:
    if state["answer"] or state["stop_reason"] is not None:
        return END
    if state["iteration_count"] >= MAX_MODEL_ITERATIONS:
        return "limit"
    return "model"


def _stop_for_iteration_limit(_: ChatState) -> dict[str, object]:
    return {"answer": LIMIT_MESSAGE, "stop_reason": "limit_reached"}


def build_chat_graph():
    graph = StateGraph(ChatState, context_schema=ChatContext)
    graph.add_node("model", _call_model)
    graph.add_node("tools", _execute_tools)
    graph.add_node("limit", _stop_for_iteration_limit)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model",
        _route_after_model,
        {"tools": "tools", "limit": "limit", END: END},
    )
    graph.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"model": "model", "limit": "limit", END: END},
    )
    graph.add_edge("limit", END)
    return graph.compile()


chat_graph = build_chat_graph()
