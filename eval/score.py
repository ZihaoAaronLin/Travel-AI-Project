"""给一次评测打分。逻辑都在 travelkb.evalkit.scoring（有测试），这里只拼报告。

    uv run python eval/score.py --run-id <名字>

读 eval/runs/<run_id>/<组>/results.jsonl、errors.jsonl，写 eval/runs/<run_id>/summary.md 并打印。
"""

import argparse
import itertools
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from travelkb.evalkit.analysis import ALPHA, HYPOTHESES, PILOT_TUNED, confirm
from travelkb.evalkit.scoring import mcnemar_exact, paired_discordant, summarize

EVAL_DIR = Path(__file__).resolve().parent
GROUP_ORDER = ["A0", "A6", "A4", "A3"]  # 报告里的顺序：从什么都没有到工具 + SOP


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="travel-kb 评测打分")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)

    run_dir = EVAL_DIR / "runs" / args.run_id
    if not run_dir.is_dir():
        print(f"没有这次运行：{run_dir}", file=sys.stderr)
        return 2
    results, errors = _load(run_dir)
    if not results:
        print(f"{run_dir} 下一行结果都没有", file=sys.stderr)
        return 2

    report = render(args.run_id, results, errors)
    (run_dir / "summary.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def render(run_id: str, results: dict[str, list[dict]], errors: dict[str, list[dict]]) -> str:
    lines = [f"# 评测结果 · {run_id}", ""]
    lines += _confirmatory(results)
    lines += _overall(results, errors)
    lines += _by_type(results)
    lines += _pairs(results)
    lines += _cost(results)
    return "\n".join(lines) + "\n"


_METRIC_LABEL = {"wrong": "答错", "noncompliant": "工具不合规"}


def _confirmatory(results) -> list[str]:
    """PREREG 第 3、4 节：只有这一节是结论，后面的都是描述性数字。"""
    full = confirm(results)
    held_out = confirm(results, exclude=PILOT_TUNED)
    lines = [
        "## 验证性检验（结论只看这一节）",
        "",
        f"按题汇总：一题两遍里错一遍就算错。三条假设一起做 Holm 校正，α = {ALPHA}。",
        f"另做一次去掉 {'、'.join(PILOT_TUNED)} 的分析（这几题试跑时用来改过 SOP），"
        "两次结论不一致时以去掉后的为准。",
        "",
    ]
    lines += _hypothesis_table("全部题", full)
    lines += _hypothesis_table(f"去掉 {'、'.join(PILOT_TUNED)}", held_out)
    lines += ["**结论：**", ""]
    for h, a, b in zip(HYPOTHESES, full, held_out, strict=True):
        if b.n == 0:
            verdict = "没有数据（对应的组没跑，或没有这类题）"
        else:
            verdict = "支持" if b.supported else "不支持（这批题上没看出差别，或方向相反）"
        note = "" if a.supported == b.supported else "（两次分析不一致，按去掉后的算）"
        lines.append(f"- {h.name}：{verdict}{note}")
    return lines + [""]


def _hypothesis_table(title: str, outcomes) -> list[str]:
    lines = [
        f"**{title}**",
        "",
        "| 假设 | 比较的事 | 题数 | 只有较差组出事 | 只有较好组出事 | p | Holm 后拒绝 | 支持 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h, r in zip(HYPOTHESES, outcomes, strict=True):
        event = f"{_METRIC_LABEL[h.metric]}：{h.worse} 应多于 {h.better}"
        lines.append(
            f"| {h.name} | {event} | {r.n} | {r.only_worse} | {r.only_better} | {r.p:.3g} "
            f"| {'是' if r.holm_reject else '否'} | {'是' if r.supported else '否'} |"
        )
    return lines + [""]


def _overall(results, errors) -> list[str]:
    lines = [
        "## 每组",
        "",
        "答错率的分母是全部有结果的行（没写 VERDICT 不算错，但占分母）；"
        "harness 失败不进分母，单列。",
        "",
        "| 组 | 行数 | 答错 | 答错率 [95% CI] | 答对 | 该弃的弃了 | 不该弃也弃了 "
        "| 没写 VERDICT | harness 失败 | 工具合规率 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for group, rows in results.items():
        s = summarize(rows)
        lo, hi = s.wrong_ci
        compliance = "—" if s.tool_compliance is None else f"{s.tool_compliance:.0%}"
        lines.append(
            f"| {group} | {s.n} | {s.counts['wrong']} | {s.wrong_rate:.0%} [{lo:.0%}, {hi:.0%}] "
            f"| {s.counts['correct']} | {s.counts['abstain_ok']} | {s.counts['abstain_unneeded']} "
            f"| {s.counts['no_verdict']} | {_harness_failures(rows, errors.get(group, []))} "
            f"| {compliance} |"
        )
    return lines + [""]


def _harness_failures(rows: list[dict], errors: list[dict]) -> str:
    """最终也没拿到结果的 (题, rep) 数；括号里是出错的总次数（含重试后成功的）。"""
    answered = {(r["qid"], r["rep"]) for r in rows}
    failed = {(e["qid"], e["rep"]) for e in errors} - answered
    return f"{len(failed)}（{len(errors)} 次）" if errors else "0"


def _by_type(results) -> list[str]:
    groups = list(results)
    types = sorted({r["type"] for rows in results.values() for r in rows})
    lines = [
        "## 按题型：答错 / 行数",
        "",
        "| 题型 | " + " | ".join(groups) + " |",
        "|---|" + "---|" * len(groups),
    ]
    for kind in types:
        cells = []
        for group in groups:
            rows = [r for r in results[group] if r["type"] == kind]
            wrong = sum(r["outcome"] == "wrong" for r in rows)
            cells.append(f"{wrong}/{len(rows)}" if rows else "—")
        lines.append(f"| {kind} | " + " | ".join(cells) + " |")
    return lines + [""]


def _pairs(results) -> list[str]:
    lines = [
        "## 配对比较（描述性：按「题 × 遍」配对，不作结论）",
        "",
        "按 (题, rep) 配对，只看「一组错、另一组没错」的对。只有 PREREG 里写的比较算检验，"
        "其余是描述。同一题的几个 rep 不独立，p 值偏乐观。",
        "",
        "| 比较 | 配对数 | 只有前者错 | 只有后者错 | p |",
        "|---|---|---|---|---|",
    ]
    for a, b in itertools.combinations(results, 2):
        only_a, only_b = paired_discordant(results[a], results[b])
        shared = {(r["qid"], r["rep"]) for r in results[a]} & {
            (r["qid"], r["rep"]) for r in results[b]
        }
        p = mcnemar_exact(only_a, only_b)
        lines.append(f"| {a} vs {b} | {len(shared)} | {only_a} | {only_b} | {p:.3g} |")
    return lines + [""]


def _cost(results) -> list[str]:
    lines = [
        "## 用量（从 result 事件读，不估算）",
        "",
        "| 组 | 总花费 USD | 平均轮数 | 平均耗时 s | 输入 token（含缓存） | 输出 token |",
        "|---|---|---|---|---|---|",
    ]
    for group, rows in results.items():
        cost = sum(r.get("cost_usd") or 0 for r in rows)
        turns = _mean([r.get("num_turns") for r in rows])
        seconds = _mean([(r.get("duration_ms") or 0) / 1000 for r in rows])
        tokens_in = sum(_input_tokens(r.get("usage") or {}) for r in rows)
        tokens_out = sum((r.get("usage") or {}).get("output_tokens", 0) for r in rows)
        lines.append(
            f"| {group} | {cost:.2f} | {turns:.1f} | {seconds:.0f} | {tokens_in} | {tokens_out} |"
        )
    return lines + [""]


def _input_tokens(usage: dict) -> int:
    # input_tokens 只算没命中缓存的部分；系统提示、工具定义多半走缓存，记在另外两个字段里。
    # 试跑时只看 input_tokens，A0 每题只有 2 个，明显不对
    fields = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(usage.get(f) or 0 for f in fields)


def _mean(values: list) -> float:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else 0.0


def _load(run_dir: Path) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    present = {d.name for d in run_dir.iterdir() if (d / "results.jsonl").exists()}
    ordered = [g for g in GROUP_ORDER if g in present] + sorted(present - set(GROUP_ORDER))
    results = {g: _read_jsonl(run_dir / g / "results.jsonl") for g in ordered}
    errors = {g: _read_jsonl(run_dir / g / "errors.jsonl") for g in ordered}
    return results, errors


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


if __name__ == "__main__":
    sys.exit(main())
