"""从 data/pois/ 读取景点 YAML。出错时在报错里带上文件名，方便定位。"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from travelkb.core.models import Poi


def load_pois(directory: Path) -> list[Poi]:
    """读取目录下所有 *.yaml，按 id 排序返回。"""
    pois = [load_poi_file(path) for path in Path(directory).glob("*.yaml")]
    return sorted(pois, key=lambda poi: poi.id)


def load_poi_file(path: Path) -> Poi:
    """读取并校验单个文件。文件名（不含扩展名）必须等于 id，这样 id 天然不会重复。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        poi = Poi.model_validate(data)
    except ValidationError as err:
        raise ValueError(f"{path.name}: 数据格式错误\n{err}") from err
    if poi.id != path.stem:
        raise ValueError(f"{path.name}: id {poi.id!r} 和文件名不一致")
    return poi
