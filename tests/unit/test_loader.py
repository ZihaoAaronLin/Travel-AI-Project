"""YAML 加载：从 data/pois/ 读出所有景点，坏文件要报出是哪个文件。"""

from pathlib import Path

import pytest

from travelkb.core.loader import load_pois

# OPEN_TIME 占位符由各测试替换：带引号是正确写法，不带引号用来测「YAML 把 10:00 读成 600」
DEMO_YAML = """\
id: POI_ID
city: Budapest
country: HU
tz: Europe/Budapest
category: museum
status: OPEN
review: draft
names:
  local: null
  en: Demo
  zh: 示例
aliases: []
rules:
  - id: r1
    valid: [2026-10-01, 2026-12-31]
    days: [MON]
    open: OPEN_TIME
    close: "18:00"
exceptions: []
source_url: https://example.org/demo
verified_at: 2026-10-01
"""


def write_poi(directory: Path, filename: str, poi_id: str, open_time: str = '"10:00"') -> None:
    text = DEMO_YAML.replace("POI_ID", poi_id).replace("OPEN_TIME", open_time)
    (directory / filename).write_text(text, encoding="utf-8")


def test_loads_every_yaml_file_sorted_by_id(tmp_path):
    write_poi(tmp_path, "b-museum.yaml", "b-museum")
    write_poi(tmp_path, "a-museum.yaml", "a-museum")

    pois = load_pois(tmp_path)

    assert [p.id for p in pois] == ["a-museum", "b-museum"]


def test_unquoted_time_in_yaml_is_rejected_and_names_the_file(tmp_path):
    write_poi(tmp_path, "demo.yaml", "demo", open_time="10:00")

    with pytest.raises(ValueError) as excinfo:
        load_pois(tmp_path)

    assert "demo.yaml" in str(excinfo.value)


def test_id_must_match_filename(tmp_path):
    write_poi(tmp_path, "demo.yaml", "another-id")

    with pytest.raises(ValueError):
        load_pois(tmp_path)


def test_ignores_non_yaml_files(tmp_path):
    write_poi(tmp_path, "demo.yaml", "demo")
    (tmp_path / "README.md").write_text("说明", encoding="utf-8")

    assert [p.id for p in load_pois(tmp_path)] == ["demo"]
