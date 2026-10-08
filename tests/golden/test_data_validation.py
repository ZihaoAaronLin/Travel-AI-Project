"""真实数据必须通过 validate_data 的全部检查：零 error、零 warning（info 只是提示）。"""

from pathlib import Path

from travelkb.core.loader import load_pois
from travelkb.core.validate import validate_pois

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"


def test_real_data_has_no_errors_or_warnings():
    issues = validate_pois(load_pois(DATA_DIR))

    problems = [f"{i.level} {i.code} {i.poi_id}: {i.message}" for i in issues if i.level != "info"]
    assert not problems, "\n".join(problems)
