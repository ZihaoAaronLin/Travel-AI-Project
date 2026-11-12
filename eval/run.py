"""跑评测。逻辑都在 travelkb.evalkit（有测试），这里只是命令行入口。

    uv run python eval/run.py --model <完整模型 ID> --run-id <名字> [选项]

先试跑 3 题（只跑没有工具的两组，读轨迹确认字段都在）：

    uv run python eval/run.py --model claude-opus-5-5 --run-id pilot \
        --groups A0,A6 --only q01,q02,q03 --reps 1

结果在 eval/runs/<run_id>/<组>/：results.jsonl、errors.jsonl、traces/。
同一条命令再跑一次就是断点续跑：已有结果的 (题, rep) 跳过，只重跑出过错的。

--model 要写完整 ID（claude-opus-5-5），不要写别名（opus）：system/init 里报的是完整 ID，
对不上会把每一题都记成隔离失败。
"""

import argparse
import dataclasses
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from travelkb.evalkit.groups import GROUPS, GroupConfig, build_command
from travelkb.evalkit.questions import Question, load_questions
from travelkb.evalkit.runner import Invocation, invoke_claude, run_group

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EVAL_DIR.parent
DRAFT_MARKER = "<!-- DRAFT"  # A3 的 SOP 还是草稿时的标记，见 groups/A3/system.md 第一行


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    questions = _select(load_questions(EVAL_DIR / "questions.yaml"), args.only, args.limit)
    groups = [GROUPS[name] for name in args.groups]

    problems = _preflight(groups, questions)
    if problems:
        for problem in problems:
            print(f"跑不了：{problem}", file=sys.stderr)
        return 2

    run_dir = EVAL_DIR / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _append_meta(run_dir, args, groups, questions)

    for group in groups:
        invoke = _with_progress(group.name)
        # 同一组里按 today 分批：有工具的组每个 today 要一份自己的 mcp.json（钉住 server 的今天）
        for today in sorted({q.today for q in questions}):
            batch = [q for q in questions if q.today == today]
            run_group(
                _for_today(group, today),
                batch,
                args.model,
                args.reps,
                run_dir / group.name,
                EVAL_DIR,
                invoke=invoke,
            )
        _report(run_dir / group.name, group.name)
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="travel-kb 评测：每题每组起一个 claude -p")
    parser.add_argument("--model", required=True, help="完整模型 ID，和 Desktop 里用的同一个")
    parser.add_argument("--run-id", required=True, help="结果目录名，如 pilot、2026-11-20")
    parser.add_argument(
        "--groups",
        default="A0,A6,A3,A4",
        type=lambda s: [g.strip() for g in s.split(",") if g.strip()],
        help="逗号分隔，默认四组都跑",
    )
    parser.add_argument("--reps", type=int, default=2, help="每题每组跑几遍（默认 2）")
    parser.add_argument(
        "--only", type=lambda s: [q.strip() for q in s.split(",") if q.strip()], help="只跑这些题号"
    )
    parser.add_argument("--limit", type=int, help="只跑前 N 题")
    args = parser.parse_args(argv)

    unknown = [g for g in args.groups if g not in GROUPS]
    if unknown:
        parser.error(f"没有这些组：{unknown}；可选 {sorted(GROUPS)}")
    if args.reps < 1:
        parser.error("--reps 至少是 1")
    return args


def _select(questions: list[Question], only: list[str] | None, limit: int | None) -> list:
    if only:
        missing = sorted(set(only) - {q.id for q in questions})
        if missing:
            raise SystemExit(f"题库里没有（或还没填）这些题：{missing}")
        questions = [q for q in questions if q.id in only]
    return questions[:limit] if limit else questions


def _preflight(groups: list[GroupConfig], questions: list[Question]) -> list[str]:
    """开跑之前把能查的都查一遍：别跑到第三组才发现缺文件，钱已经花了一半。"""
    problems = []
    if not questions:
        problems.append("一道题都没选中")
    if shutil.which("claude") is None:
        problems.append("PATH 里找不到 claude")
    if any(g.mcp_config for g in groups):
        if shutil.which("uv") is None:
            problems.append("PATH 里找不到 uv（有工具的组要用它启动 travelkb）")
        if _today_env_name() is None:
            problems.append(
                "server 还不支持 TRAVELKB_TODAY（测试等 Aaron 审）：不钉住今天，"
                "A3 / A4 会带着 STALE 提醒作答，结果不可比。先只跑 A0、A6"
            )

    for group in groups:
        prompt = EVAL_DIR / group.system_prompt
        if not prompt.exists():
            problems.append(f"{group.name} 缺系统提示 {prompt}")
        elif DRAFT_MARKER in prompt.read_text(encoding="utf-8"):
            problems.append(f"{group.name} 的系统提示还是草稿：{prompt}（换成 Project 指令原文）")
    return problems


def _today_env_name() -> str | None:
    # 名字只在 server 里定义一次；server 还没实现时 import 失败，正好用来拦住 A3 / A4
    try:
        from travelkb.server import TODAY_ENV
    except ImportError:
        return None
    return TODAY_ENV


def _for_today(group: GroupConfig, today: dt.date) -> GroupConfig:
    """有工具的组：换成这一天专用的 mcp.json。文件名带日期，两个 run.py 同时跑也不会互相覆盖。"""
    if not group.mcp_config:
        return group
    relative = f"groups/mcp-{today.isoformat()}.json"
    _write_mcp_config(EVAL_DIR / relative, today)
    return dataclasses.replace(group, mcp_config=relative)


def _write_mcp_config(path: Path, today: dt.date) -> None:
    # 绝对路径：claude 在空的临时目录里启动，相对路径找不到项目
    config = {
        "mcpServers": {
            "travelkb": {
                "command": shutil.which("uv"),
                "args": ["--directory", str(PROJECT_DIR), "run", "travelkb-server"],
                "env": {_today_env_name(): today.isoformat()},
            }
        }
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_meta(run_dir: Path, args, groups: list[GroupConfig], questions: list[Question]):
    """每次启动记一行：哪个 commit、哪个 claude 版本、跑了什么。PREREG 和结果对得上的证据。"""
    meta = {
        "started_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "model": args.model,
        "groups": [g.name for g in groups],
        "reps": args.reps,
        "questions": [q.id for q in questions],
        "git_commit": _run(["git", "-C", str(PROJECT_DIR), "rev-parse", "HEAD"]),
        # 不算 eval/runs/：上一次运行留下的结果本来就没提交，算进去会永远是 dirty
        "git_dirty": bool(
            _run(["git", "-C", str(PROJECT_DIR), "status", "--porcelain", "--", ".", ":!eval/runs"])
        ),
        "claude_version": _run(["claude", "--version"]),
        "sample_command": build_command(groups[0], questions[0], args.model, EVAL_DIR),
    }
    with (run_dir / "meta.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def _with_progress(label: str):
    """包一层 invoke_claude：每跑完一次往 stderr 打一行，长跑时知道它还活着。"""
    count = 0

    def invoke(cmd: list[str], cwd: Path) -> Invocation:
        nonlocal count
        count += 1
        question = cmd[cmd.index("-p") + 1]
        started = time.monotonic()
        result = invoke_claude(cmd, cwd)
        elapsed = time.monotonic() - started
        print(
            f"[{label}] #{count} exit={result.returncode} {elapsed:.0f}s  {question[:30]}",
            file=sys.stderr,
        )
        return result

    return invoke


def _report(group_dir: Path, name: str) -> None:
    results = _count_lines(group_dir / "results.jsonl")
    errors = _count_lines(group_dir / "errors.jsonl")
    print(f"[{name}] 结果 {results} 行，harness 错误 {errors} 次 → {group_dir}", file=sys.stderr)


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


if __name__ == "__main__":
    sys.exit(main())
