"""题库加载：eval/questions.yaml 的格式校验（DESIGN.md 第 2 节）。"""

from datetime import date
from pathlib import Path

import pytest

from travelkb.evalkit.questions import load_questions

FULL = """\
- id: q01
  type: weekly_closed
  question: 下周一去示例博物馆，开门吗？
  today: 2026-10-10
  gold: {verdict: CLOSED, facts: 周一闭馆}
  in_kb: true
  expected_tools: [resolve_poi, is_open]
  gold_sources: [https://example.org/hours]
  gold_archive: null
  gold_checked_at: 2026-10-10
"""

SLOT = """\
- {id: q11, type: open_day, question: null}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "questions.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_filled_questions(tmp_path):
    [q] = load_questions(write(tmp_path, FULL))

    assert (q.id, q.type, q.gold_verdict, q.in_kb) == ("q01", "weekly_closed", "CLOSED", True)
    assert q.today == date(2026, 10, 10)
    assert q.expected_tools == ["resolve_poi", "is_open"]
    assert q.gold_facts == "周一闭馆"


def test_unfilled_slots_are_skipped(tmp_path):
    assert [q.id for q in load_questions(write(tmp_path, FULL + SLOT))] == ["q01"]


def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="q01"):
        load_questions(write(tmp_path, FULL + FULL))


@pytest.mark.parametrize("bad", ["MAYBE", "NOT_FOUND", "closed"])
def test_gold_verdict_must_be_one_of_four(tmp_path, bad):
    with pytest.raises(ValueError, match="verdict"):
        load_questions(write(tmp_path, FULL.replace("verdict: CLOSED", f"verdict: {bad}")))


def test_filled_question_needs_today_and_gold(tmp_path):
    with pytest.raises(ValueError):
        load_questions(write(tmp_path, FULL.replace("  today: 2026-10-10\n", "")))


def test_expected_tools_default_to_empty(tmp_path):
    [q] = load_questions(
        write(tmp_path, FULL.replace("  expected_tools: [resolve_poi, is_open]\n", ""))
    )

    assert q.expected_tools == []
