"""判分（DESIGN.md 第 5 节）：规则判分矩阵、工具合规、Wilson 区间、McNemar 精确检验、汇总。"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from travelkb.evalkit.questions import VERDICTS

Outcome = Literal["correct", "wrong", "abstain_ok", "abstain_unneeded", "no_verdict"]
OUTCOMES: tuple[Outcome, ...] = ("correct", "wrong", "abstain_ok", "abstain_unneeded", "no_verdict")

_DEFINITE = {"OPEN", "CLOSED"}
_ABSTAIN = {"UNKNOWN", "AMBIGUOUS"}


def classify(gold: str, answer: str | None) -> Outcome:
    """判分矩阵。主指标是 wrong：给了确定答案但错了，或该弃 / 该问的时候给了确定答案。"""
    if gold not in VERDICTS:
        raise ValueError(f"gold 必须是 {VERDICTS}，收到 {gold!r}")
    if answer is None:
        return "no_verdict"
    if answer not in VERDICTS:
        raise ValueError(f"answer 必须是 {VERDICTS} 或 None，收到 {answer!r}")

    if gold in _DEFINITE:
        if answer == gold:
            return "correct"
        return "wrong" if answer in _DEFINITE else "abstain_unneeded"
    if answer in _DEFINITE:
        return "wrong"  # gold 是 UNKNOWN / AMBIGUOUS：不该下确定结论
    # gold UNKNOWN：弃答或追问都算谨慎；gold AMBIGUOUS：追问才算对，弃答偏保守但没错
    if gold == "AMBIGUOUS" and answer == "AMBIGUOUS":
        return "correct"
    return "abstain_ok"


def tool_compliant(tool_calls: Sequence[str], expected: Sequence[str]) -> bool | None:
    """期望的工具是否都调过，且首次出现的先后和期望一致（先 resolve 再 is_open）。

    没有期望工具时（无工具的组、或题目没要求）不适用，返回 None。
    """
    if not expected:
        return None
    positions = []
    for tool in expected:
        if tool not in tool_calls:
            return False
        positions.append(tool_calls.index(tool))
    return positions == sorted(positions)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """比例 k/n 的 Wilson 95% 区间。小样本、比例接近 0 或 1 时比正态近似可靠。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = n + z * z
    center = (k + z * z / 2) / denom
    half = z * math.sqrt(p * (1 - p) * n + z * z / 4) / denom
    lo = 0.0 if k == 0 else max(0.0, center - half)
    hi = 1.0 if k == n else min(1.0, center + half)
    return (lo, hi)


def mcnemar_exact(b: int, c: int) -> float:
    """配对数据的 McNemar 精确检验（双侧）。

    b、c 是「只有一组错」的题数；两边都错 / 都对的题不提供信息，不进检验。
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_discordant(rows_a: Sequence[dict], rows_b: Sequence[dict]) -> tuple[int, int]:
    """按 (题, rep) 配对，数「A 错 B 不错」和「A 不错 B 错」的题数，给 McNemar 用。"""
    wrong_a = {(r["qid"], r["rep"]): r["outcome"] == "wrong" for r in rows_a}
    wrong_b = {(r["qid"], r["rep"]): r["outcome"] == "wrong" for r in rows_b}
    shared = wrong_a.keys() & wrong_b.keys()
    b = sum(1 for key in shared if wrong_a[key] and not wrong_b[key])
    c = sum(1 for key in shared if wrong_b[key] and not wrong_a[key])
    return (b, c)


@dataclass(frozen=True)
class GroupSummary:
    n: int
    counts: dict[str, int]
    wrong_rate: float  # 分母是全部有结果的行：no_verdict 不算错，但也占分母
    wrong_ci: tuple[float, float]
    correct_rate: float
    tool_compliance: float | None  # 只对有工具的行算；没有这样的行就是 None


def summarize(rows: Sequence[dict]) -> GroupSummary:
    counts = {outcome: sum(r["outcome"] == outcome for r in rows) for outcome in OUTCOMES}
    n = len(rows)
    judged = [r["tool_compliant"] for r in rows if r.get("tool_compliant") is not None]
    return GroupSummary(
        n=n,
        counts=counts,
        wrong_rate=counts["wrong"] / n if n else 0.0,
        wrong_ci=wilson(counts["wrong"], n),
        correct_rate=counts["correct"] / n if n else 0.0,
        tool_compliance=sum(judged) / len(judged) if judged else None,
    )
