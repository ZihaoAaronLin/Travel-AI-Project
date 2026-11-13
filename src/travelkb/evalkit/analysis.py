"""验证性检验（eval/PREREG.md 第 3、4 节）。报告里的结论只认这里。

和 scoring.py 的区别：scoring 按「题 × 遍」配对，只当描述性数字。同一题的两遍不独立，
当成两个样本会让 p 值偏乐观，所以这里先把每组的每道题汇总成一个结果，再配对检验。
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from travelkb.evalkit.scoring import mcnemar_exact

ALPHA = 0.05
H5_TYPES = (
    "season_boundary",
    "monthly_rule",
    "exception_closed",
    "exception_changed_hours",
    "same_name_in_city",
)
PILOT_TUNED = ("q01", "q02", "q03", "q04")  # 试跑时用来改过 SOP 的题，另做一次去掉它们的分析

Metric = Literal["wrong", "noncompliant"]


@dataclass(frozen=True)
class Hypothesis:
    name: str
    better: str  # 假设里应该更好的组
    worse: str  # 假设里应该更差的组
    metric: Metric  # 数的是哪件「坏事」
    types: tuple[str, ...] | None = None  # 只看这些题型；None 是全部题


HYPOTHESES = (
    Hypothesis("H1", better="A3", worse="A0", metric="wrong"),
    Hypothesis("H5", better="A3", worse="A6", metric="wrong", types=H5_TYPES),
    Hypothesis("H3", better="A3", worse="A4", metric="noncompliant"),
)


@dataclass(frozen=True)
class QuestionView:
    type: str
    wrong: bool  # 任一遍答错就算错：答错的代价高
    compliant: bool | None  # 两遍都合规才算合规；这题不期望工具时为 None


@dataclass(frozen=True)
class HypothesisResult:
    name: str
    n: int  # 两组都有结果、参与比较的题数
    only_worse: int  # 只有「较差组」出事的题数：支持假设的方向
    only_better: int  # 只有「较好组」出事的题数：反对假设的方向
    p: float
    holm_reject: bool
    supported: bool  # Holm 后拒绝原假设，并且方向和假设一致


def by_question(rows: Sequence[dict]) -> dict[str, QuestionView]:
    """一组的 results.jsonl 行 → 每道题一个结果。"""
    reps: dict[str, list[dict]] = {}
    for row in rows:
        reps.setdefault(row["qid"], []).append(row)
    return {qid: _view(group) for qid, group in reps.items()}


def _view(rows: list[dict]) -> QuestionView:
    judged = [r["tool_compliant"] for r in rows if r.get("tool_compliant") is not None]
    return QuestionView(
        type=rows[0]["type"],
        wrong=any(r["outcome"] == "wrong" for r in rows),
        compliant=all(judged) if judged else None,
    )


def discordant(a: Mapping[str, bool | None], b: Mapping[str, bool | None]) -> tuple[int, int, int]:
    """(只有 a 为真的题数, 只有 b 为真的题数, 参与比较的题数)。只看两边都有值的题。"""
    shared = [q for q in a.keys() & b.keys() if a[q] is not None and b[q] is not None]
    only_a = sum(1 for q in shared if a[q] and not b[q])
    only_b = sum(1 for q in shared if b[q] and not a[q])
    return only_a, only_b, len(shared)


def holm(pvalues: Mapping[str, float], alpha: float = ALPHA) -> dict[str, bool]:
    """Holm–Bonferroni：p 从小到大，第 i 个（从 0 数）和 alpha / (m - i) 比。

    一旦有一个不过，后面的全不拒绝。
    """
    decisions = {name: False for name in pvalues}
    ordered = sorted(pvalues, key=pvalues.get)
    for i, name in enumerate(ordered):
        if pvalues[name] > alpha / (len(ordered) - i):
            break
        decisions[name] = True
    return decisions


def confirm(
    results: Mapping[str, Sequence[dict]], exclude: Collection[str] = ()
) -> list[HypothesisResult]:
    """三条假设各做一次 McNemar，再一起做 Holm。results 是 {组名: results.jsonl 的行}。

    某组没跑时那条假设 n = 0、p = 1，但仍占 Holm 的一个名额：校正强度事先定死。
    """
    views = {
        group: {q: v for q, v in by_question(rows).items() if q not in exclude}
        for group, rows in results.items()
    }
    counts = {h.name: _count(h, views) for h in HYPOTHESES}
    pvalues = {name: mcnemar_exact(worse, better) for name, (worse, better, _) in counts.items()}
    rejected = holm(pvalues)

    return [
        HypothesisResult(
            name=h.name,
            n=counts[h.name][2],
            only_worse=counts[h.name][0],
            only_better=counts[h.name][1],
            p=pvalues[h.name],
            holm_reject=rejected[h.name],
            supported=rejected[h.name] and counts[h.name][0] > counts[h.name][1],
        )
        for h in HYPOTHESES
    ]


def _count(h: Hypothesis, views: Mapping[str, Mapping[str, QuestionView]]) -> tuple[int, int, int]:
    if h.worse not in views or h.better not in views:
        return 0, 0, 0  # 这组没跑：没有数据（mcnemar_exact(0, 0) = 1）
    return discordant(_events(h, views[h.worse]), _events(h, views[h.better]))


def _events(h: Hypothesis, view: Mapping[str, QuestionView]) -> dict[str, bool | None]:
    """每道题有没有发生假设关心的那件「坏事」；题型不在范围内的不参与。"""
    picked = {q: v for q, v in view.items() if h.types is None or v.type in h.types}
    if h.metric == "wrong":
        return {q: v.wrong for q, v in picked.items()}
    return {q: None if v.compliant is None else not v.compliant for q, v in picked.items()}
