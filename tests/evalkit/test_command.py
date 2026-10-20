"""每组的 `claude -p` 命令行（DESIGN.md 第 3 节）。flag 按 CLI 文档核对过，这里把它们钉死。"""

from pathlib import Path

import pytest

from travelkb.evalkit.groups import GROUPS, GroupConfig, build_command

MODEL = "claude-opus-5-5"
TRAVELKB_TOOLS = [
    "mcp__travelkb__resolve_poi",
    "mcp__travelkb__is_open",
    "mcp__travelkb__check_day_plan",
    "mcp__travelkb__find_open_pois",
]


def flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    (tmp_path / "groups" / "A3").mkdir(parents=True)
    (tmp_path / "groups" / "base.md").write_text("base", encoding="utf-8")
    (tmp_path / "groups" / "A3" / "system.md").write_text("base + SOP", encoding="utf-8")
    (tmp_path / "groups" / "mcp.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_four_groups_are_defined():
    assert set(GROUPS) == {"A0", "A3", "A4", "A6"}


def test_common_flags(eval_dir, questions):
    cmd = build_command(GROUPS["A0"], questions[0], MODEL, eval_dir)

    assert cmd[0] == "claude"
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == questions[0].question
    assert flag_value(cmd, "--model") == MODEL
    assert flag_value(cmd, "--system-prompt-file") == str(eval_dir / "groups" / "base.md")
    assert "2026-10-10" in flag_value(cmd, "--append-system-prompt")  # 「今天」钉死
    assert flag_value(cmd, "--output-format") == "stream-json"
    assert "--verbose" in cmd
    assert "--no-session-persistence" in cmd
    assert "--disable-slash-commands" in cmd
    assert flag_value(cmd, "--permission-prompts") == "none"
    assert flag_value(cmd, "--max-turns") == "6"


def test_a0_has_no_tools_at_all(eval_dir, questions):
    cmd = build_command(GROUPS["A0"], questions[0], MODEL, eval_dir)

    assert flag_value(cmd, "--tools") == ""
    # --tools "" 不影响 MCP 工具（文档原话），所以要双保险
    assert "--strict-mcp-config" in cmd and "--mcp-config" not in cmd
    assert flag_value(cmd, "--disallowedTools") == "mcp__*"
    assert "--allowedTools" not in cmd


def test_a6_has_only_web_search(eval_dir, questions):
    cmd = build_command(GROUPS["A6"], questions[0], MODEL, eval_dir)

    assert flag_value(cmd, "--tools") == "WebSearch,WebFetch"
    # --permission-prompts none 下会弹提示的一律被拒：要用的工具必须预先放行
    assert flag_value(cmd, "--allowedTools") == "WebSearch,WebFetch"
    assert "--mcp-config" not in cmd and "--strict-mcp-config" in cmd


@pytest.mark.parametrize("group", ["A3", "A4"])
def test_tool_groups_load_only_travelkb(eval_dir, questions, group):
    cmd = build_command(GROUPS[group], questions[0], MODEL, eval_dir)

    assert flag_value(cmd, "--tools") == ""
    assert flag_value(cmd, "--mcp-config") == str(eval_dir / "groups" / "mcp.json")
    assert "--strict-mcp-config" in cmd
    assert flag_value(cmd, "--allowedTools") == ",".join(TRAVELKB_TOOLS)


def test_a3_uses_sop_and_a4_uses_base_prompt(eval_dir, questions):
    a3 = build_command(GROUPS["A3"], questions[0], MODEL, eval_dir)
    a4 = build_command(GROUPS["A4"], questions[0], MODEL, eval_dir)

    assert flag_value(a3, "--system-prompt-file") == str(eval_dir / "groups" / "A3" / "system.md")
    assert flag_value(a4, "--system-prompt-file") == str(eval_dir / "groups" / "base.md")


def test_missing_system_prompt_file_is_an_error(eval_dir, questions):
    (eval_dir / "groups" / "A3" / "system.md").unlink()

    with pytest.raises(FileNotFoundError, match="system.md"):
        build_command(GROUPS["A3"], questions[0], MODEL, eval_dir)


def test_group_config_knows_what_must_not_appear(eval_dir):
    # init 校验用：这些工具出现在 system/init 里就说明隔离失败
    assert GROUPS["A0"].forbidden_tools == ("WebSearch", "WebFetch", "Bash", "mcp__")
    assert GROUPS["A6"].forbidden_tools == ("Bash", "mcp__")
    assert GROUPS["A3"].forbidden_tools == ("WebSearch", "WebFetch", "Bash")
    assert GROUPS["A3"].mcp_servers == ("travelkb",) and GROUPS["A0"].mcp_servers == ()
    assert isinstance(GROUPS["A0"], GroupConfig)
