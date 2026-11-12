"""对照组的配置和每组的 `claude -p` 命令行（DESIGN.md 第 3 节）。

flag 按 code.claude.com/docs/en/cli-reference 核对：
- `--tools ""` 只关内置工具，不影响 MCP 工具 → 没有 MCP 的组再加 `--disallowedTools "mcp__*"` 双保险
- `--strict-mcp-config` 只认 `--mcp-config` 里的 server；不给 `--mcp-config` 就一个都不加载
- `--permission-prompts none` 下会弹提示的一律被拒 → 要用的工具必须预先 `--allowedTools`
- `--system-prompt-file` 替换整个系统提示，`--append-system-prompt` 再接「今天」
"""

from dataclasses import dataclass
from pathlib import Path

from travelkb.evalkit.questions import Question

MAX_TURNS = 6  # resolve → is_open → 回答用不到 6 轮；到上限算 harness 错误，不算答错

TRAVELKB_TOOLS = (
    "mcp__travelkb__resolve_poi",
    "mcp__travelkb__is_open",
    "mcp__travelkb__check_day_plan",
    "mcp__travelkb__find_open_pois",
)


@dataclass(frozen=True)
class GroupConfig:
    name: str
    system_prompt: str  # 相对 eval/ 的路径
    builtin_tools: tuple[str, ...]  # --tools 的值；() 表示全关
    mcp_config: str | None  # 相对 eval/ 的路径；None 表示不加载任何 MCP server
    mcp_servers: tuple[str, ...]  # system/init 里应该出现、且只能出现的 server
    allowed_tools: tuple[str, ...]  # 预先放行，免得无人应答的权限提示把调用拒掉
    forbidden_tools: tuple[str, ...]  # system/init 的 tools 里出现这些前缀 = 隔离失败


_NO_TOOLS = ("WebSearch", "WebFetch", "Bash", "mcp__")

GROUPS: dict[str, GroupConfig] = {
    "A0": GroupConfig(
        name="A0",
        system_prompt="groups/base.md",
        builtin_tools=(),
        mcp_config=None,
        mcp_servers=(),
        allowed_tools=(),
        forbidden_tools=_NO_TOOLS,
    ),
    "A6": GroupConfig(
        name="A6",
        system_prompt="groups/base.md",
        builtin_tools=("WebSearch", "WebFetch"),
        mcp_config=None,
        mcp_servers=(),
        allowed_tools=("WebSearch", "WebFetch"),
        forbidden_tools=("Bash", "mcp__"),
    ),
    "A3": GroupConfig(
        name="A3",
        system_prompt="groups/A3/system.md",  # base + Aaron 的 SOP
        builtin_tools=(),
        mcp_config="groups/mcp.json",
        mcp_servers=("travelkb",),
        allowed_tools=TRAVELKB_TOOLS,
        forbidden_tools=("WebSearch", "WebFetch", "Bash"),
    ),
    "A4": GroupConfig(
        name="A4",
        system_prompt="groups/base.md",  # 同 A3 但不给 SOP
        builtin_tools=(),
        mcp_config="groups/mcp.json",
        mcp_servers=("travelkb",),
        allowed_tools=TRAVELKB_TOOLS,
        forbidden_tools=("WebSearch", "WebFetch", "Bash"),
    ),
}


def build_command(group: GroupConfig, question: Question, model: str, eval_dir: Path) -> list[str]:
    """一题一组的完整命令行。所有组只差工具相关的几个 flag，其余完全相同。"""
    prompt_file = Path(eval_dir) / group.system_prompt
    if not prompt_file.exists():
        raise FileNotFoundError(f"系统提示文件不存在：{prompt_file}")

    cmd = [
        "claude",
        "-p",
        question.question,
        "--model",
        model,
        "--system-prompt-file",
        str(prompt_file),
        "--append-system-prompt",
        f"今天是 {question.today.isoformat()}（景点当地日期）。",
        "--tools",
        ",".join(group.builtin_tools),
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--max-turns",
        str(MAX_TURNS),
        "--permission-prompts",
        "none",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if group.mcp_config:
        cmd += ["--mcp-config", str(Path(eval_dir) / group.mcp_config)]
    else:
        cmd += ["--disallowedTools", "mcp__*"]
    if group.allowed_tools:
        cmd += ["--allowedTools", ",".join(group.allowed_tools)]
    return cmd
