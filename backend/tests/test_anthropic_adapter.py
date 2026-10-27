from insaaf.llm import Message, ToolCall, ToolSpec
from insaaf.llm.anthropic_chat import FALLBACK_BETA, MIN_MAX_TOKENS, AnthropicChat, _to_anthropic
from insaaf.processing.enrich import INSIGHTS_SCHEMA

TOOL = ToolSpec("search_case_law", "search", {"type": "object", "properties": {}})


def test_conversion_replays_raw_and_groups_tool_results() -> None:
    raw = [{"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "tool_use", "id": "t1", "name": "x", "input": {}}]
    system, msgs = _to_anthropic(
        [
            Message("system", "SYS"),
            Message("user", "q"),
            Message("assistant", "", tool_calls=[ToolCall("t1", "x", {})], raw=raw),
            Message("tool", "r1", tool_call_id="t1"),
            Message("tool", "r2", tool_call_id="t2"),
            Message("user", "finalize"),
        ]
    )
    assert system == "SYS"
    assert msgs[1] == {"role": "assistant", "content": raw}  # thinking block preserved verbatim
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    blocks = msgs[2]["content"]
    assert [b["type"] for b in blocks] == ["tool_result", "tool_result", "text"]


def test_request_shape_for_opus() -> None:
    llm = AnthropicChat("claude-opus-5-5", api_key="x", effort="high")
    kw = llm._kwargs([Message("user", "q")], max_tokens=1500, tools=[TOOL], json_schema=INSIGHTS_SCHEMA)
    assert "temperature" not in kw
    assert kw["max_tokens"] == MIN_MAX_TOKENS
    assert kw["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": INSIGHTS_SCHEMA}}
    assert kw["betas"] == [FALLBACK_BETA] and kw["fallbacks"] == "default"
    assert kw["tools"][0]["input_schema"] == TOOL.parameters


def test_no_fallback_for_haiku() -> None:
    kw = AnthropicChat("claude-haiku-5-5", api_key="x", effort="low")._kwargs([Message("user", "q")], 100)
    assert "fallbacks" not in kw and "betas" not in kw
    assert kw["output_config"] == {"effort": "low"}
