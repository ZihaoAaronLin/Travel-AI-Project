"""验证性检验（eval/PREREG.md 第 3、4 节）：按题汇总、Holm 校正、三条假设、
去掉 q01–q04 的敏感性分析。

和 scoring.py 的区别：scoring 的 summarize / paired_discordant 按「题 × 遍」算，只当描述性数字；
这里按题算（同一题的两遍不独立，不能当成两个样本），结论只认这里。

接口：travelkb.evalkit.analysis
- by_question(rows) -> {qid: QuestionView(type, wrong, compliant)}
  wrong：任一遍答错就是 True；compliant：没有工具期望时为 None，否则两遍都合规才是 True
- discordant(a, b) -> (only_a, only_b, n)：a、b 是 {qid: bool | None}，只看两边都有值的题；
  only_a = a 为 True 而 b 为 False 的题数；n = 参与比较的题数
- holm(pvalues, alpha=0.05) -> {名字: 是否拒绝原假设}
- HYPOTHESES：H1、H5、H3 三条，顺序和 PREREG 一致；H5_TYPES：H5 的题型清单；PILOT_TUNED：q01–q04
- confirm(results, exclude=()) -> [HypothesisResult(...)]，字段：
  name, n, only_worse, only_better, p, holm_reject, supported
  results 是 {组名: results.jsonl 的行}；only_worse = 只有「假设里较差的那组」出事的题数
  supported = Holm 校正后拒绝原假设，且方向和假设一致
  没数据的假设（那组没跑）也占 Holm 的一个名额（p = 1）：校正强度事先定死，不因为少跑一组就放松
"""

import pytest

from travelkb.evalkit.analysis import (
    H5_TYPES,
    HYPOTHESES,
    PILOT_TUNED,
    by_question,
    confirm,
    discordant,
    holm,
)


def row(qid, outcome, rep=0, type="open_day", tool_compliant=None):
    return {
        "qid": qid,
        "rep": rep,
        "type": type,
        "outcome": outcome,
        "tool_compliant": tool_compliant,
    }


def two_reps(qid, first, second, **kwargs):
    return [row(qid, first, rep=0, **kwargs), row(qid, second, rep=1, **kwargs)]


def by_name(results):
    return {r.name: r for r in results}


# ---- 按题汇总 ----


def test_one_wrong_rep_makes_the_question_wrong():
    view = by_question(two_reps("q11", "correct", "wrong"))

    assert view["q11"].wrong is True


@pytest.mark.parametrize("outcomes", [("correct", "correct"), ("abstain_ok", "no_verdict")])
def test_question_without_wrong_reps_is_not_wrong(outcomes):
    assert by_question(two_reps("q11", *outcomes))["q11"].wrong is False


def test_both_reps_wrong_still_counts_once():
    # 不按「题 × 遍」：两遍都错也只是一道错题
    view = by_question(two_reps("q11", "wrong", "wrong") + two_reps("q12", "correct", "correct"))

    assert sorted(view) == ["q11", "q12"]
    assert [view[q].wrong for q in ("q11", "q12")] == [True, False]


def test_compliance_needs_both_reps():
    rows = [
        row("q11", "correct", rep=0, tool_compliant=True),
        row("q11", "correct", rep=1, tool_compliant=False),
        *two_reps("q12", "correct", "correct", tool_compliant=True),
        *two_reps("q13", "correct", "correct"),  # 无工具的组：不适用
    ]
    view = by_question(rows)

    assert [view[q].compliant for q in ("q11", "q12", "q13")] == [False, True, None]


def test_type_is_carried_over():
    assert (
        by_question([row("q11", "correct", type="season_boundary")])["q11"].type
        == "season_boundary"
    )


# ---- 配对计数 ----


def test_discordant_counts_only_shared_questions_with_values():
    a = {"q1": True, "q2": True, "q3": False, "q4": True, "q5": None}
    b = {"q1": False, "q2": True, "q3": True, "q5": True, "q6": False}

    # q4 只在 a 里、q6 只在 b 里、q5 在 a 里不适用：都不参与
    assert discordant(a, b) == (1, 1, 3)


# ---- Holm ----


def test_holm_stops_at_the_first_failure():
    # 从小到大：0.01 ≤ 0.05/3 拒绝；0.03 > 0.05/2 停下，之后的 0.04 也不拒绝
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": True, "b": False, "c": False}


def test_holm_can_reject_all():
    assert holm({"a": 0.01, "b": 0.02, "c": 0.04}) == {"a": True, "b": True, "c": True}


# ---- 假设的定义和 PREREG 一致 ----


def test_hypotheses_match_prereg():
    assert [(h.name, h.better, h.worse, h.metric) for h in HYPOTHESES] == [
        ("H1", "A3", "A0", "wrong"),
        ("H5", "A3", "A6", "wrong"),
        ("H3", "A3", "A4", "noncompliant"),
    ]
    assert set(H5_TYPES) == {
        "season_boundary",
        "monthly_rule",
        "exception_closed",
        "exception_changed_hours",
        "same_name_in_city",
    }
    assert set(PILOT_TUNED) == {"q01", "q02", "q03", "q04"}


# ---- confirm ----


def scenario(a0_wrong, a3_wrong, qids, type="open_day"):
    """A0、A3 在 qids 上各跑两遍；a0_wrong / a3_wrong 里的题在那一组第一遍答错。"""
    results = {"A0": [], "A3": []}
    for qid in qids:
        for group, wrong in (("A0", a0_wrong), ("A3", a3_wrong)):
            first = "wrong" if qid in wrong else "correct"
            results[group] += two_reps(qid, first, "correct", type=type)
    return results


QIDS = [f"q{n:02d}" for n in range(11, 31)]


def test_h1_supported_with_seven_to_zero():
    # 7:0 的双侧 p = 0.0156，低于 Holm 最严的门槛 0.05 / 3
    results = by_name(confirm(scenario(a0_wrong=QIDS[:7], a3_wrong=[], qids=QIDS)))

    h1 = results["H1"]
    assert (h1.n, h1.only_worse, h1.only_better) == (20, 7, 0)
    assert h1.p == pytest.approx(2 / 2**7)
    assert h1.holm_reject is True
    assert h1.supported is True


def test_six_to_zero_is_not_enough_after_holm():
    # 不校正 p = 0.031 < 0.05；但 Holm 下最小的 p 要和 0.0167 比
    h1 = by_name(confirm(scenario(a0_wrong=QIDS[:6], a3_wrong=[], qids=QIDS)))["H1"]

    assert h1.p == pytest.approx(2 / 2**6)
    assert h1.supported is False


def test_wrong_direction_is_never_supported():
    # p 一样小，但是 A3 更差：照实报告，不算支持
    h1 = by_name(confirm(scenario(a0_wrong=[], a3_wrong=QIDS[:7], qids=QIDS)))["H1"]

    assert (h1.only_worse, h1.only_better) == (0, 7)
    assert h1.holm_reject is True
    assert h1.supported is False


def test_h5_only_counts_its_question_types():
    results = {"A3": [], "A6": []}
    for qid in QIDS[:10]:  # 前 10 题是换季题，A6 错
        results["A6"] += two_reps(qid, "wrong", "correct", type="season_boundary")
        results["A3"] += two_reps(qid, "correct", "correct", type="season_boundary")
    for qid in QIDS[10:]:  # 后 10 题是普通开闭馆，A3 错：H5 不该看到
        results["A6"] += two_reps(qid, "correct", "correct", type="open_day")
        results["A3"] += two_reps(qid, "wrong", "correct", type="open_day")

    h5 = by_name(confirm(results))["H5"]

    assert (h5.n, h5.only_worse, h5.only_better) == (10, 10, 0)


def test_h3_compares_noncompliance_on_questions_with_expected_tools():
    results = {"A3": [], "A4": []}
    for i, qid in enumerate(QIDS[:12]):
        results["A3"] += two_reps(qid, "correct", "correct", tool_compliant=True)
        results["A4"] += two_reps(qid, "correct", "correct", tool_compliant=i >= 8)  # 前 8 题不合规
    for qid in QIDS[12:]:  # 不期望工具的题（两组都是 None）：不参与
        results["A3"] += two_reps(qid, "correct", "correct")
        results["A4"] += two_reps(qid, "correct", "correct")

    h3 = by_name(confirm(results))["H3"]

    assert (h3.n, h3.only_worse, h3.only_better) == (12, 8, 0)


def test_group_not_run_gives_an_empty_result():
    # 只跑了 A0、A3：H5、H3 没有数据，不能算支持，也不能让程序崩
    results = by_name(confirm(scenario(a0_wrong=QIDS[:7], a3_wrong=[], qids=QIDS)))

    for name in ("H5", "H3"):
        assert results[name].n == 0
        assert results[name].p == 1.0
        assert results[name].supported is False


def test_sensitivity_analysis_drops_pilot_tuned_questions():
    qids = ["q01", "q02", "q03", "q04", *QIDS]
    results = scenario(a0_wrong=["q01", "q02", "q03", "q04", *QIDS[:3]], a3_wrong=[], qids=qids)

    full = by_name(confirm(results))["H1"]
    held_out = by_name(confirm(results, exclude=PILOT_TUNED))["H1"]

    assert (full.n, full.only_worse) == (24, 7)
    assert (held_out.n, held_out.only_worse) == (20, 3)
    assert full.supported is True
    assert held_out.supported is False  # 两个结论不一致时以去掉后的为准（PREREG 第 8 节）
