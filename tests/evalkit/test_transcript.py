"""解析一次 `claude -p` 的 stream-json 轨迹：拿 VERDICT、工具调用顺序、用量；校验 system/init 的隔离。"""

import pytest

from travelkb.evalkit.groups import GROUPS
from travelkb.evalkit.transcript import check_init, extract_verdict, parse_transcript

from .conftest import answer, init_event, result_event, text_event, tool_use_event

# ---- VERDICT 行 ----


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("周一闭馆。\n\nVERDICT: CLOSED", "CLOSED"),
        ("VERDICT: OPEN", "OPEN"),
        ("**VERDICT: UNKNOWN**", "UNKNOWN"),  # 模型爱加粗
        ("verdict:  ambiguous  ", "AMBIGUOUS"),  # 大小写、空格不计较（清单：判分别太死板）
        ("VERDICT: `CLOSED`", "CLOSED"),
        ("先说 VERDICT: OPEN\n后来改口\nVERDICT: CLOSED", "CLOSED"),  # 多行取最后一行
        ("VERDICT: CLOSED\n\n以上。", "CLOSED"),  # 不在末行也认
    ],
)
def test_extract_verdict(text, expected):
    assert extract_verdict(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "周一闭馆。",
        "",
        "VERDICT: MAYBE",
        "VERDICT: NOT_FOUND",
        "VERDICT: CLOSED OPEN",
        "结论：CLOSED",
    ],
)
def test_missing_or_invalid_verdict_is_none(text):
    assert extract_verdict(text) is None


# ---- 整条轨迹 ----


def test_parse_collects_tools_text_and_usage():
    events = [
        init_event(
            mcp_servers=["travelkb"], tools=["mcp__travelkb__resolve_poi", "mcp__travelkb__is_open"]
        ),
        tool_use_event("mcp__travelkb__resolve_poi", query="示例博物馆"),
        tool_use_event("mcp__travelkb__is_open", poi_id="demo-museum", date="2026-10-12"),
        text_event("周一闭馆。"),
        result_event(answer("CLOSED"), num_turns=3, cost=0.0421, duration_ms=8200),
    ]

    t = parse_transcript(events)

    assert t.model == "claude-opus-5-5"
    assert t.mcp_servers == ["travelkb"]
    assert t.tool_calls == ["resolve_poi", "is_open"]  # 去掉 mcp__travelkb__ 前缀，顺序保留
    assert t.verdict == "CLOSED"
    assert t.final_text.endswith("VERDICT: CLOSED")
    assert (t.num_turns, t.cost_usd, t.duration_ms) == (3, 0.0421, 8200)
    assert t.usage == {"input_tokens": 1200, "output_tokens": 80}
    assert t.error is None


def test_builtin_tool_names_are_kept_as_is():
    events = [
        init_event(tools=["WebSearch", "WebFetch"]),
        tool_use_event("WebSearch", query="x"),
        result_event("VERDICT: OPEN"),
    ]

    assert parse_transcript(events).tool_calls == ["WebSearch"]


@pytest.mark.parametrize(
    ("events", "error"),
    [
        (
            [init_event(), result_event("", is_error=True, subtype="error_during_execution")],
            "result_error",
        ),
        ([init_event(), result_event("", subtype="error_max_turns")], "max_turns"),
        ([init_event(), text_event("只说了一半")], "no_result"),
        ([result_event("VERDICT: OPEN")], "no_init"),
    ],
)
def test_broken_transcripts_report_an_error_class(events, error):
    assert parse_transcript(events).error == error


def test_empty_answer_is_no_verdict_not_an_error():
    # 「没答」≠「出错」≠「答错」：空回答是模型的产出，归 no_verdict
    t = parse_transcript([init_event(), result_event("")])

    assert t.error is None
    assert t.verdict is None


# ---- system/init 校验：隔离失败要当 harness 错误 ----


def test_init_passes_when_isolation_holds():
    init = init_event(mcp_servers=["travelkb"], tools=["mcp__travelkb__resolve_poi"])

    assert check_init(init, GROUPS["A3"], "claude-opus-5-5") == []


def test_init_flags_wrong_model():
    problems = check_init(init_event(model="claude-sonnet-5-5"), GROUPS["A0"], "claude-opus-5-5")

    assert any("model" in p for p in problems)


def test_init_flags_unexpected_mcp_server():
    # A0 不该有任何 MCP server；A3 只该有 travelkb
    assert check_init(init_event(mcp_servers=["travelkb"]), GROUPS["A0"], "claude-opus-5-5")
    assert check_init(
        init_event(mcp_servers=["travelkb", "notion"]), GROUPS["A3"], "claude-opus-5-5"
    )


@pytest.mark.parametrize(
    ("group", "leaked_tool"),
    [("A0", "WebSearch"), ("A0", "mcp__travelkb__is_open"), ("A6", "Bash"), ("A3", "WebFetch")],
)
def test_init_flags_forbidden_tools(group, leaked_tool):
    problems = check_init(
        init_event(mcp_servers=GROUPS[group].mcp_servers, tools=[leaked_tool]),
        GROUPS[group],
        "claude-opus-5-5",
    )

    assert any(leaked_tool in p for p in problems)


def test_init_ignores_harmless_builtins():
    # 像 EndConversation 这类关不掉的内置工具不算泄漏
    init = init_event(tools=["EndConversation"])

    assert check_init(init, GROUPS["A0"], "claude-opus-5-5") == []
