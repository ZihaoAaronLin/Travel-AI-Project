"""解析一次 `claude -p --output-format stream-json` 的轨迹，并校验 system/init 的隔离。

事件形状按 code.claude.com/docs/en/headless：第一条 system/init（model、tools、mcp_servers），
中间 assistant 事件的 content 里有 tool_use 块，最后一条 result（result 文本、usage、cost、轮数）。
字段一律用 .get：缺了不崩，记成错误。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from travelkb.evalkit.groups import GroupConfig
from travelkb.evalkit.questions import VERDICTS

# 去掉行首行尾的加粗 / 反引号 / 下划线之后，整行只能是 "VERDICT: <一个词>"；
# 值两边也允许再包一层标记（"VERDICT: `CLOSED`"、"VERDICT: **OPEN**"）
_VERDICT_LINE = re.compile(r"^verdict\s*[:：]\s*[*_`]*([A-Za-z_]+)[*_`]*$", re.IGNORECASE)
_MARKUP = "*_`"

# 像 EndConversation 这类关不掉的内置工具不算泄漏；只有组里明确禁止的前缀才算
TranscriptError = str  # result_error / max_turns / no_result / no_init


@dataclass
class Transcript:
    init: dict | None = None
    model: str | None = None
    mcp_servers: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)  # 去掉 mcp__<server>__ 前缀，顺序保留
    final_text: str = ""
    verdict: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    usage: dict | None = None
    error: TranscriptError | None = None


def extract_verdict(text: str) -> str | None:
    """最后一次出现的 VERDICT 行。容忍加粗、反引号、大小写；值不在四选一里算没写。"""
    found = None
    for raw in text.splitlines():
        line = raw.strip().strip(_MARKUP).strip()
        match = _VERDICT_LINE.match(line)
        if match:
            found = match.group(1).strip(_MARKUP).upper()
    return found if found in VERDICTS else None


def parse_transcript(events: Sequence[dict]) -> Transcript:
    t = Transcript()
    result = None
    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init" and t.init is None:
            t.init = event
            t.model = event.get("model")
            t.mcp_servers = [s.get("name") for s in event.get("mcp_servers", []) if s.get("name")]
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content", []):
                if block.get("type") == "tool_use":
                    t.tool_calls.append(_short_tool_name(block.get("name", "")))
        elif kind == "result":
            result = event

    if t.init is None:
        t.error = "no_init"
    elif result is None:
        t.error = "no_result"
    else:
        t.final_text = result.get("result") or ""
        t.verdict = extract_verdict(t.final_text)
        t.num_turns = result.get("num_turns")
        t.cost_usd = result.get("total_cost_usd")
        t.duration_ms = result.get("duration_ms")
        t.usage = result.get("usage")
        subtype = result.get("subtype")
        if subtype == "error_max_turns":
            t.error = "max_turns"
        elif result.get("is_error") or (subtype and subtype != "success"):
            t.error = "result_error"
    return t


def check_init(init: dict, group: GroupConfig, expected_model: str) -> list[str]:
    """隔离校验：模型对不对、MCP server 是不是只有该有的、有没有组里禁止的工具。返回问题清单。"""
    problems = []
    model = init.get("model")
    if model != expected_model:
        problems.append(f"model 是 {model!r}，要求 {expected_model!r}")

    servers = sorted(s.get("name", "?") for s in init.get("mcp_servers", []))
    if servers != sorted(group.mcp_servers):
        problems.append(
            f"mcp_servers 是 {servers}，{group.name} 组要求 {sorted(group.mcp_servers)}"
        )

    for tool in init.get("tools", []):
        if any(tool.startswith(prefix) for prefix in group.forbidden_tools):
            problems.append(f"{group.name} 组不该有工具 {tool}")
    return problems


def _short_tool_name(name: str) -> str:
    # MCP 工具叫 mcp__<server>__<tool>；内置工具（WebSearch）原样保留
    if name.startswith("mcp__"):
        return name.split("__", 2)[-1]
    return name
