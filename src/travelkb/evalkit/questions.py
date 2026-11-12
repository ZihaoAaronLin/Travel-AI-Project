"""题库 eval/questions.yaml 的加载和格式校验（DESIGN.md 第 2 节）。"""

import datetime as dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["OPEN", "CLOSED", "UNKNOWN", "AMBIGUOUS"]
VERDICTS: tuple[str, ...] = ("OPEN", "CLOSED", "UNKNOWN", "AMBIGUOUS")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str  # 题型，报告里的分组键
    question: str
    today: dt.date  # 注入给模型的「今天」，让「下周一」可判定
    gold_verdict: Verdict
    gold_facts: str = ""
    in_kb: bool = True
    expected_tools: list[str] = Field(default_factory=list)  # 有工具的组，下结论前至少该调过的
    gold_sources: list[str] = Field(default_factory=list)
    gold_archive: str | None = None
    gold_checked_at: dt.date | None = None


def load_questions(path: Path) -> list[Question]:
    """读题库。question 为 null 的是还没填的空位，跳过；填了的必须完整。"""
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    questions = [_parse(entry) for entry in entries if entry.get("question") is not None]

    ids = [q.id for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"题号重复：{duplicates}")
    return questions


def _parse(entry: dict) -> Question:
    qid = entry.get("id", "?")
    gold = entry.get("gold") or {}
    verdict = gold.get("verdict")
    # 先于 pydantic 单独检查，报错信息才能说清是 verdict 的问题、收到了什么
    if verdict not in VERDICTS:
        raise ValueError(f"{qid}: gold.verdict 必须是 {'/'.join(VERDICTS)}，收到 {verdict!r}")
    if entry.get("today") is None:
        raise ValueError(f"{qid}: 缺 today（注入给模型的「今天」）")

    fields = {k: v for k, v in entry.items() if k != "gold"}
    return Question(gold_verdict=verdict, gold_facts=str(gold.get("facts", "")), **fields)
