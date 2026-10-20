"""判分（DESIGN.md 第 5 节）：判分矩阵的每一格、工具合规、Wilson 区间、McNemar 精确检验、汇总。"""

import math

import pytest

from travelkb.evalkit.scoring import (
    classify,
    mcnemar_exact,
    paired_discordant,
    summarize,
    tool_compliant,
    wilson,
)

DEFINITE = ["OPEN", "CLOSED"]

# ---- 判分矩阵：gold × 模型答案 ----


@pytest.mark.parametrize("gold", DEFINITE)
def test_definite_gold(gold):
    other = "CLOSED" if gold == "OPEN" else "OPEN"

    assert classify(gold, gold) == "correct"
    assert classify(gold, other) == "wrong"
    assert classify(gold, "UNKNOWN") == "abstain_unneeded"
    assert classify(gold, "AMBIGUOUS") == "abstain_unneeded"


def test_unknown_gold():
    # 该说不知道却给了确定答案 = 答错；追问也算谨慎
    assert classify("UNKNOWN", "OPEN") == "wrong"
    assert classify("UNKNOWN", "CLOSED") == "wrong"
    assert classify("UNKNOWN", "UNKNOWN") == "abstain_ok"
    assert classify("UNKNOWN", "AMBIGUOUS") == "abstain_ok"


def test_ambiguous_gold():
    # 自动挑了一个就是答错；说不知道偏保守但没错；追问才算对
    assert classify("AMBIGUOUS", "OPEN") == "wrong"
    assert classify("AMBIGUOUS", "CLOSED") == "wrong"
    assert classify("AMBIGUOUS", "UNKNOWN") == "abstain_ok"
    assert classify("AMBIGUOUS", "AMBIGUOUS") == "correct"


@pytest.mark.parametrize("gold", DEFINITE + ["UNKNOWN", "AMBIGUOUS"])
def test_no_verdict_is_its_own_outcome(gold):
    assert classify(gold, None) == "no_verdict"


def test_classify_rejects_unknown_labels():
    with pytest.raises(ValueError):
        classify("MAYBE", "OPEN")
    with pytest.raises(ValueError):
        classify("OPEN", "MAYBE")


# ---- 工具合规（诊断指标）----


def test_compliant_when_expected_tools_called_in_order():
    assert tool_compliant(["resolve_poi", "is_open"], ["resolve_poi", "is_open"]) is True
    assert (
        tool_compliant(
            ["resolve_poi", "resolve_poi", "is_open", "is_open"], ["resolve_poi", "is_open"]
        )
        is True
    )


def test_not_compliant_when_a_tool_is_skipped_or_order_is_wrong():
    assert tool_compliant(["is_open"], ["resolve_poi", "is_open"]) is False
    assert (
        tool_compliant(["is_open", "resolve_poi"], ["resolve_poi", "is_open"]) is False
    )  # 先猜 id 再消歧
    assert tool_compliant([], ["resolve_poi"]) is False


def test_compliance_is_undefined_for_groups_without_tools():
    assert tool_compliant([], []) is None
    assert tool_compliant(["WebSearch"], []) is None


# ---- 统计 ----


def test_wilson_interval_known_value():
    lo, hi = wilson(3, 10)

    assert (round(lo, 3), round(hi, 3)) == (0.108, 0.603)


def test_wilson_edge_cases():
    assert wilson(0, 0) == (0.0, 1.0)  # 没数据：什么都说不了
    lo, hi = wilson(0, 30)
    assert lo == 0.0 and 0.1 < hi < 0.2  # 0/30 的上界约 11%，不是 0


@pytest.mark.parametrize(
    ("b", "c", "p"),
    [
        (0, 0, 1.0),  # 没有不一致的题，差异无从谈起
        (1, 1, 1.0),
        (8, 0, 2 / 256),  # 8 题全是一边错 → 2 × 0.5^8
        (3, 1, 0.625),  # 2 × P(X ≤ 1 | n=4) = 2 × 5/16
    ],
)
def test_mcnemar_exact(b, c, p):
    assert math.isclose(mcnemar_exact(b, c), p, rel_tol=1e-9)
    assert mcnemar_exact(c, b) == mcnemar_exact(b, c)


def test_mcnemar_never_exceeds_one():
    assert mcnemar_exact(5, 5) == 1.0


def test_paired_discordant_counts_by_question_and_rep():
    a = [
        row("q1", 0, "wrong"),
        row("q2", 0, "correct"),
        row("q3", 0, "wrong"),
        row("q4", 0, "abstain_ok"),
    ]
    b = [
        row("q1", 0, "correct"),
        row("q2", 0, "wrong"),
        row("q3", 0, "wrong"),
        row("q5", 0, "wrong"),
    ]

    # q1：A 错 B 对；q2：A 对 B 错；q3 两边都错不算；q4/q5 只有一边有数据，不配对
    assert paired_discordant(a, b) == (1, 1)


def test_summarize_counts_and_rates():
    rows = [
        row("q1", 0, "correct"),
        row("q2", 0, "wrong"),
        row("q3", 0, "wrong"),
        row("q4", 0, "abstain_ok"),
        row("q5", 0, "no_verdict"),
    ]

    s = summarize(rows)

    assert s.n == 5
    assert s.counts == {
        "correct": 1,
        "wrong": 2,
        "abstain_ok": 1,
        "abstain_unneeded": 0,
        "no_verdict": 1,
    }
    assert s.wrong_rate == 0.4  # 分母是全部有结果的题；no_verdict 不算错但也占分母
    assert s.wrong_ci == wilson(2, 5)


def test_summarize_tool_compliance_only_over_rows_where_it_applies():
    rows = [
        row("q1", 0, "correct", compliant=True),
        row("q2", 0, "wrong", compliant=False),
        row("q3", 0, "correct", compliant=None),
    ]

    assert summarize(rows).tool_compliance == 0.5


def test_summarize_without_tool_groups_has_no_compliance():
    assert summarize([row("q1", 0, "correct", compliant=None)]).tool_compliance is None


def row(qid, rep, outcome, compliant=None):
    return {"qid": qid, "rep": rep, "outcome": outcome, "tool_compliant": compliant}
