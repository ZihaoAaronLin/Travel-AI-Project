"""评测 harness 测试的假数据：手写的 stream-json 事件 + 题目。

事件形状按 code.claude.com/docs/en/headless 写（system/init、assistant、result）。
真实字段名在 Aaron 跑 3 题试验时再对一遍——解析器只用 .get，字段缺了不会崩，但会记成 harness 错误。
"""

from datetime import date

import pytest

from travelkb.evalkit.questions import Question


def init_event(model="claude-opus-5-5", mcp_servers=(), tools=()):
    return {
        "type": "system",
        "subtype": "init",
        "model": model,
        "tools": list(tools),
        "mcp_servers": [{"name": name, "status": "connected"} for name in mcp_servers],
        "session_id": "s-1",
    }


def tool_use_event(name, **arguments):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": f"tu-{name}", "name": name, "input": arguments}],
        },
    }


def text_event(text):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def result_event(
    text, *, is_error=False, subtype="success", num_turns=1, cost=0.01, duration_ms=1500
):
    return {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "result": text,
        "num_turns": num_turns,
        "total_cost_usd": cost,
        "duration_ms": duration_ms,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
        "session_id": "s-1",
    }


def answer(verdict, body="按官网信息判断。"):
    """一段带 VERDICT 行的回答。"""
    return f"{body}\n\nVERDICT: {verdict}"


@pytest.fixture
def questions():
    return [
        Question(
            id="q01",
            type="weekly_closed",
            question="下周一去示例博物馆，开门吗？",
            today=date(2026, 10, 10),
            gold_verdict="CLOSED",
            gold_facts="周一闭馆",
            in_kb=True,
            expected_tools=["resolve_poi", "is_open"],
        ),
        Question(
            id="q02",
            type="not_in_kb",
            question="示例温泉几点开门？",
            today=date(2026, 10, 10),
            gold_verdict="UNKNOWN",
            gold_facts="库里没有",
            in_kb=False,
            expected_tools=["resolve_poi"],
        ),
        Question(
            id="q03",
            type="same_name_in_city",
            question="下周去示例城的美术馆，哪天开？",
            today=date(2026, 10, 10),
            gold_verdict="AMBIGUOUS",
            gold_facts="两家都叫美术馆",
            in_kb=True,
            expected_tools=["resolve_poi"],
        ),
    ]
