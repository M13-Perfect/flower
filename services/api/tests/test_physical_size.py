import json
import shutil
from pathlib import Path

import pytest

from app.domain import DomainError
from app.domain.exports.dxf import _physical_size_mm
from app.domain.templates.physical import get_physical_size, update_physical_size


REPO_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "templates"
    / "products"
    / "birth-flower-card.json"
)


@pytest.fixture()
def project_root(tmp_path, monkeypatch) -> Path:
    products = tmp_path / "templates" / "products"
    products.mkdir(parents=True)
    shutil.copy(REPO_TEMPLATE, products / "birth-flower-card.json")
    monkeypatch.setenv("FLOWER_PROJECT_ROOT", str(tmp_path))
    return tmp_path


def test_get_physical_size_derives_height_from_canvas_ratio(project_root) -> None:
    size = get_physical_size("birth-flower-card")
    assert size.width_mm == 80
    assert size.height_derived is True
    # 画布 3000x3000 -> 等比推导高度等于宽度
    assert size.height_mm == pytest.approx(80)


def test_update_physical_size_roundtrip_and_template_is_single_source(project_root) -> None:
    update_physical_size("birth-flower-card", 60)
    size = get_physical_size("birth-flower-card")
    assert size.width_mm == 60
    assert size.height_mm == pytest.approx(60)
    # 数据源就是模板文件本身,批量引擎读到的必然是同一份
    raw = json.loads(
        (project_root / "templates" / "products" / "birth-flower-card.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw["exportSettings"]["physical"]["widthMm"] == 60
    assert "heightMm" not in raw["exportSettings"]["physical"]


def test_update_physical_size_flows_into_dxf_exporter_scale(project_root) -> None:
    """UI 改值 -> 模板 -> 文档 exportSettings -> DXF 物理尺寸,全链路同一数值。"""
    update_physical_size("birth-flower-card", 40)
    raw = json.loads(
        (project_root / "templates" / "products" / "birth-flower-card.json").read_text(
            encoding="utf-8"
        )
    )
    document = {"canvas": raw["canvas"], "exportSettings": raw["exportSettings"]}
    assert _physical_size_mm(document) == (40, pytest.approx(40))


def test_update_physical_size_unlocked_height_persists(project_root) -> None:
    update_physical_size("birth-flower-card", 50, 70)
    size = get_physical_size("birth-flower-card")
    assert size.height_derived is False
    assert size.height_mm == 70


def test_update_physical_size_rejects_non_positive(project_root) -> None:
    with pytest.raises(DomainError):
        update_physical_size("birth-flower-card", 0)
    with pytest.raises(DomainError):
        update_physical_size("birth-flower-card", 50, -1)
