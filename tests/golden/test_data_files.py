"""真实数据的完整性：data/pois/ 里每个文件都必须能通过数据模型校验。

10 条金标准等 Aaron 写好 tests/golden/cases.yaml 再加；这里只保证数据本身没格式错误。
"""

from pathlib import Path

from travelkb.core.loader import load_pois

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"


def test_every_real_poi_file_loads():
    pois = load_pois(DATA_DIR)

    assert pois, "data/pois/ 下没有任何景点"
