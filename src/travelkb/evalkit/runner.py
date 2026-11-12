"""跑题：每题每组起一个全新的 `claude -p`，存轨迹，写 results.jsonl / errors.jsonl，可断点续跑。

调 claude 的那一层（invoke）是注入进来的：正式跑用 invoke_claude（子进程），测试用假的。
基础设施的错（崩溃、限流、隔离失败、到轮数上限）只进 errors.jsonl，不占结果行——
否则重跑时跳不过去，还会把 harness 的问题算成模型答错。
"""

import json
import random
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from travelkb.evalkit.groups import GroupConfig, build_command
from travelkb.evalkit.questions import Question
from travelkb.evalkit.scoring import classify, tool_compliant
from travelkb.evalkit.transcript import check_init, parse_transcript

MAX_ATTEMPTS = 3  # 只有限流才重试
DEFAULT_BACKOFF_S = 30.0
CASE_TIMEOUT_S = 300  # 单题硬上限：卡住的流不会无限等


@dataclass(frozen=True)
class Invocation:
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


Invoke = Callable[[list[str], Path], Invocation]


def invoke_claude(cmd: list[str], cwd: Path) -> Invocation:
    """正式的调用：子进程跑 claude，超时算一次失败（stderr 标 timeout）。"""
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=CASE_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as err:
        return Invocation(-1, _text(err.stdout), f"timeout after {CASE_TIMEOUT_S}s", CASE_TIMEOUT_S)
    return Invocation(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)


def run_group(
    group: GroupConfig,
    questions: Sequence[Question],
    model: str,
    reps: int,
    out_dir: Path,
    eval_dir: Path,
    invoke: Invoke = invoke_claude,
    backoff_s: float = DEFAULT_BACKOFF_S,
) -> None:
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    done = _finished_keys(out_dir / "results.jsonl")

    for question in questions:
        for rep in range(reps):
            if (question.id, rep) in done:
                continue
            _run_one(group, question, model, rep, out_dir, eval_dir, invoke, backoff_s)


def _run_one(group, question, model, rep, out_dir, eval_dir, invoke, backoff_s) -> None:
    cmd = build_command(group, question, model, eval_dir)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = _invoke_in_fresh_dir(invoke, cmd)
        error, detail, transcript = _diagnose(result, group, model)
        if error is None:
            trace = f"traces/{question.id}_rep{rep}.jsonl"
            (out_dir / trace).write_text(result.stdout, encoding="utf-8")
            _append(
                out_dir / "results.jsonl", _row(group, question, rep, transcript, attempt, trace)
            )
            return

        trace = f"traces/{question.id}_rep{rep}_attempt{attempt}.err.jsonl"
        (out_dir / trace).write_text(result.stdout, encoding="utf-8")
        _append(
            out_dir / "errors.jsonl",
            {
                "qid": question.id,
                "group": group.name,
                "rep": rep,
                "attempt": attempt,
                "error": error,
                "detail": detail,
                "stderr": result.stderr[-2000:],
                "trace": trace,
            },
        )
        if error != "rate_limit" or attempt == MAX_ATTEMPTS:
            return
        time.sleep(backoff_s * attempt * random.uniform(0.8, 1.2))  # 带抖动的退避


def _invoke_in_fresh_dir(invoke: Invoke, cmd: list[str]) -> Invocation:
    # 每次一个空目录：没有上一题留下的文件，也不会读到项目里的 CLAUDE.md / .mcp.json
    workdir = Path(tempfile.mkdtemp(prefix="travelkb-eval-"))
    try:
        return invoke(cmd, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _diagnose(result: Invocation, group: GroupConfig, model: str):
    """把一次调用归成：成功（返回轨迹）或某一类 harness 错误。"""
    if result.returncode != 0:
        if "timeout" in result.stderr:
            return "timeout", result.stderr, None
        if _looks_rate_limited(result.stderr + result.stdout):
            return "rate_limit", result.stderr, None
        return "nonzero_exit", f"exit {result.returncode}", None

    transcript = parse_transcript(_events(result.stdout))
    if transcript.error is not None:
        return transcript.error, transcript.final_text[:500], None
    problems = check_init(transcript.init, group, model)
    if problems:
        return "isolation", "；".join(problems), None
    return None, "", transcript


def _row(group, question, rep, t, attempts, trace) -> dict:
    # 没有工具的组谈不上合规；有工具的组按题目期望的工具判
    expected = question.expected_tools if group.mcp_servers else []
    return {
        "qid": question.id,
        "group": group.name,
        "rep": rep,
        "type": question.type,
        "question": question.question,
        "gold": question.gold_verdict,
        "verdict": t.verdict,
        "outcome": classify(question.gold_verdict, t.verdict),
        "tool_calls": t.tool_calls,
        "tool_compliant": tool_compliant(t.tool_calls, expected),
        "model": t.model,
        "num_turns": t.num_turns,
        "usage": t.usage,
        "cost_usd": t.cost_usd,
        "duration_ms": t.duration_ms,
        "attempts": attempts,
        "trace": trace,
    }


def _finished_keys(results: Path) -> set[tuple[str, int]]:
    if not results.exists():
        return set()
    return {(r["qid"], r["rep"]) for r in _read_jsonl(results)}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 偶发的非 JSON 行（警告之类）跳过；真缺事件会被 parse_transcript 报出来
    return events


def _looks_rate_limited(text: str) -> bool:
    lowered = text.lower()
    return "429" in lowered or "rate limit" in lowered or "rate_limit" in lowered


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value
