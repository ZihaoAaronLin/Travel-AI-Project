"""跑题的 runner：调 `claude -p`（这里用假的）、存轨迹、写 results.jsonl / errors.jsonl、断点续跑。

一分钱不花：invoke 是注入进来的函数，测试里返回手写的 stream-json。
清单要求的两条烟雾测试也在这里：喂 gold 答案全对 → 答错率 0；喂空输出 → 全是 no_verdict 而不是答错。
"""

import json
from pathlib import Path

import pytest

from travelkb.evalkit.groups import GROUPS
from travelkb.evalkit.runner import Invocation, run_group
from travelkb.evalkit.scoring import summarize

from .conftest import answer, init_event, result_event, tool_use_event

MODEL = "claude-opus-5-5"


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    (tmp_path / "groups" / "A3").mkdir(parents=True)
    for name in ("base.md", "A3/system.md"):
        (tmp_path / "groups" / name).write_text("prompt", encoding="utf-8")
    (tmp_path / "groups" / "mcp.json").write_text("{}", encoding="utf-8")
    return tmp_path


class FakeClaude:
    """按 (题, rep) 顺序吐出预先写好的轨迹，并记录每次调用的命令和工作目录。"""

    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.calls = []

    def __call__(self, cmd: list[str], cwd: Path) -> Invocation:
        self.calls.append((cmd, cwd))
        events = self.transcripts.pop(0)
        if events == "crash":
            return Invocation(returncode=1, stdout="", stderr="boom", duration_s=0.1)
        if events == "rate_limited":
            return Invocation(
                returncode=1, stdout="", stderr="429 rate limit exceeded", duration_s=0.1
            )
        return Invocation(
            returncode=0,
            stdout="\n".join(json.dumps(e) for e in events),
            stderr="",
            duration_s=0.5,
        )


def a3_transcript(verdict, tools=("mcp__travelkb__resolve_poi", "mcp__travelkb__is_open")):
    return [
        init_event(mcp_servers=["travelkb"], tools=list(tools)),
        *[tool_use_event(t) for t in tools],
        result_event(answer(verdict), num_turns=len(tools) + 1),
    ]


def a0_transcript(text):
    return [init_event(), result_event(text)]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---- 正常一轮 ----


def test_writes_one_result_row_per_question_with_trace(eval_dir, questions):
    fake = FakeClaude(
        [a3_transcript("CLOSED"), a3_transcript("UNKNOWN"), a3_transcript("AMBIGUOUS")]
    )
    out = eval_dir / "runs" / "r1" / "A3"

    run_group(GROUPS["A3"], questions, MODEL, reps=1, out_dir=out, eval_dir=eval_dir, invoke=fake)

    rows = read_jsonl(out / "results.jsonl")
    assert [(r["qid"], r["rep"], r["outcome"]) for r in rows] == [
        ("q01", 0, "correct"),
        ("q02", 0, "abstain_ok"),
        ("q03", 0, "correct"),
    ]
    first = rows[0]
    assert first["group"] == "A3" and first["type"] == "weekly_closed"
    assert (first["gold"], first["verdict"]) == ("CLOSED", "CLOSED")
    assert first["tool_calls"] == ["resolve_poi", "is_open"] and first["tool_compliant"] is True
    assert first["model"] == MODEL and first["num_turns"] == 3
    assert first["usage"]["input_tokens"] == 1200 and first["cost_usd"] == 0.01
    assert first["attempts"] == 1
    assert (out / first["trace"]).exists()  # 轨迹原样保存，路径相对 out_dir
    assert not (out / "errors.jsonl").exists()


def test_each_invocation_runs_in_a_fresh_empty_directory(eval_dir, questions):
    fake = FakeClaude(
        [a3_transcript("CLOSED"), a3_transcript("UNKNOWN"), a3_transcript("AMBIGUOUS")]
    )

    run_group(
        GROUPS["A3"],
        questions,
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    cwds = [cwd for _, cwd in fake.calls]
    assert len(set(cwds)) == 3  # 每次一个新目录（清单：状态隔离）
    assert all(cwd != eval_dir and not str(cwd).startswith(str(eval_dir)) for cwd in cwds)
    assert fake.calls[0][0][0] == "claude" and questions[0].question in fake.calls[0][0]


def test_reps_produce_separate_rows_and_traces(eval_dir, questions):
    fake = FakeClaude([a3_transcript("CLOSED"), a3_transcript("OPEN")])

    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=2,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    rows = read_jsonl(eval_dir / "o" / "results.jsonl")
    assert [(r["rep"], r["outcome"]) for r in rows] == [(0, "correct"), (1, "wrong")]
    assert len({r["trace"] for r in rows}) == 2


# ---- 出错：进 errors.jsonl，不进结果；限流重试 ----


def test_crash_goes_to_errors_not_results(eval_dir, questions):
    fake = FakeClaude(["crash", a3_transcript("UNKNOWN"), a3_transcript("AMBIGUOUS")])

    run_group(
        GROUPS["A3"],
        questions,
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    assert [r["qid"] for r in read_jsonl(eval_dir / "o" / "results.jsonl")] == ["q02", "q03"]
    [err] = read_jsonl(eval_dir / "o" / "errors.jsonl")
    assert (err["qid"], err["rep"], err["error"]) == ("q01", 0, "nonzero_exit")
    assert "boom" in err["stderr"]


def test_rate_limit_is_retried_with_the_attempt_recorded(eval_dir, questions):
    fake = FakeClaude(["rate_limited", a3_transcript("CLOSED")])

    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
        backoff_s=0,
    )

    [row] = read_jsonl(eval_dir / "o" / "results.jsonl")
    assert row["outcome"] == "correct" and row["attempts"] == 2
    [err] = read_jsonl(eval_dir / "o" / "errors.jsonl")  # 失败的那次也留痕
    assert err["error"] == "rate_limit" and err["attempt"] == 1


def test_rate_limit_gives_up_after_three_attempts(eval_dir, questions):
    fake = FakeClaude(["rate_limited", "rate_limited", "rate_limited"])

    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
        backoff_s=0,
    )

    assert not (eval_dir / "o" / "results.jsonl").exists()
    assert len(read_jsonl(eval_dir / "o" / "errors.jsonl")) == 3


def test_failed_isolation_is_a_harness_error(eval_dir, questions):
    leaked = [
        init_event(mcp_servers=["travelkb", "notion"], tools=["mcp__travelkb__is_open"]),
        result_event(answer("CLOSED")),
    ]
    fake = FakeClaude([leaked])

    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    assert not (eval_dir / "o" / "results.jsonl").exists()
    [err] = read_jsonl(eval_dir / "o" / "errors.jsonl")
    assert err["error"] == "isolation" and "notion" in err["detail"]


def test_max_turns_is_a_harness_error_not_a_wrong_answer(eval_dir, questions):
    fake = FakeClaude(
        [[init_event(mcp_servers=["travelkb"]), result_event("", subtype="error_max_turns")]]
    )

    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    [err] = read_jsonl(eval_dir / "o" / "errors.jsonl")
    assert err["error"] == "max_turns"


# ---- 断点续跑 ----


def test_resume_skips_rows_already_in_results(eval_dir, questions):
    out = eval_dir / "o"
    run_group(
        GROUPS["A3"],
        questions[:2],
        MODEL,
        reps=1,
        out_dir=out,
        eval_dir=eval_dir,
        invoke=FakeClaude([a3_transcript("CLOSED"), a3_transcript("UNKNOWN")]),
    )

    second = FakeClaude([a3_transcript("AMBIGUOUS")])
    run_group(GROUPS["A3"], questions, MODEL, reps=1, out_dir=out, eval_dir=eval_dir, invoke=second)

    assert len(second.calls) == 1  # 只跑了 q03
    assert [r["qid"] for r in read_jsonl(out / "results.jsonl")] == ["q01", "q02", "q03"]


def test_resume_reruns_questions_that_only_errored(eval_dir, questions):
    out = eval_dir / "o"
    run_group(
        GROUPS["A3"],
        questions[:1],
        MODEL,
        reps=1,
        out_dir=out,
        eval_dir=eval_dir,
        invoke=FakeClaude(["crash"]),
    )

    second = FakeClaude([a3_transcript("CLOSED")])
    run_group(
        GROUPS["A3"], questions[:1], MODEL, reps=1, out_dir=out, eval_dir=eval_dir, invoke=second
    )

    assert len(second.calls) == 1
    assert [r["outcome"] for r in read_jsonl(out / "results.jsonl")] == ["correct"]


# ---- 烟雾测试（清单）：oracle 全对、null 全 no_verdict ----


def test_oracle_scores_zero_wrong(eval_dir, questions):
    fake = FakeClaude([a0_transcript(answer(q.gold_verdict)) for q in questions])

    run_group(
        GROUPS["A0"],
        questions,
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    s = summarize(read_jsonl(eval_dir / "o" / "results.jsonl"))
    assert s.wrong_rate == 0.0
    assert s.counts["correct"] + s.counts["abstain_ok"] == 3
    assert s.tool_compliance is None  # A0 没工具，合规率不适用


def test_null_output_is_all_no_verdict_not_wrong(eval_dir, questions):
    fake = FakeClaude([a0_transcript("") for _ in questions])

    run_group(
        GROUPS["A0"],
        questions,
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    s = summarize(read_jsonl(eval_dir / "o" / "results.jsonl"))
    assert s.counts["no_verdict"] == 3 and s.wrong_rate == 0.0


def test_always_open_baseline_is_mostly_wrong(eval_dir, questions):
    # 清单：常数基线要失败——三题 gold 分别是 CLOSED / UNKNOWN / AMBIGUOUS，全答 OPEN 全错
    fake = FakeClaude([a0_transcript(answer("OPEN")) for _ in questions])

    run_group(
        GROUPS["A0"],
        questions,
        MODEL,
        reps=1,
        out_dir=eval_dir / "o",
        eval_dir=eval_dir,
        invoke=fake,
    )

    assert summarize(read_jsonl(eval_dir / "o" / "results.jsonl")).wrong_rate == 1.0
