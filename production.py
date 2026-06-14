"""单元素「生产参数」容器与回落链。

背景（见 docs/superpowers/plans/2026-06-14-layer-material-library-system.md §5）：
旧体系里生产参数（画布/位置/尺寸/字号）是 **全局一份** `EngravingLayout`。
新体系让生产参数 **随图层变动**，并按下面的优先级自顶向下回落：

    图层 override → 素材默认 → 库默认 → 产品默认 → 全局硬默认

本模块只负责「一个元素的可选参数 + 合并规则」，不依赖 models / UI，
方便单测与被 models.Layer / material_library / 解析器复用，避免循环依赖。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ProductionParams:
    """单元素生产参数；所有字段可选，``None`` 表示「该层不覆盖，回落到下一层」。

    刻意全部可选：库/素材清单通常只声明自己关心的几个字段（例如只给宽高），
    其余留空由更低优先级补齐。几何坐标沿用画布本地像素，与 ``EngravingLayout`` 同坐标系。
    """

    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    rotation: float | None = None
    font_size: int | None = None  # 文本类素材用；图像素材留 None
    lock_aspect_ratio: bool | None = None

    def merge_onto(self, base: "ProductionParams | None") -> "ProductionParams":
        """把「本实例的非 None 字段」覆盖到 ``base`` 上，返回合并后的新实例。

        语义：self 优先级 **高于** base。self 某字段为 None 时保留 base 的值。
        ``base`` 为 None 视为空参数。
        """
        if base is None:
            base = ProductionParams()
        merged: dict[str, Any] = {}
        for spec in fields(self):
            own = getattr(self, spec.name)
            merged[spec.name] = own if own is not None else getattr(base, spec.name)
        return ProductionParams(**merged)

    def is_empty(self) -> bool:
        """所有字段都为 None（纯回落，不覆盖任何东西）。"""
        return all(getattr(self, spec.name) is None for spec in fields(self))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "ProductionParams":
        """从 library.json / 配置等松散字典构造；忽略未知键，类型非法的字段降级为 None。"""
        if not data:
            return cls()
        known = {spec.name for spec in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known or value is None:
                continue
            kwargs[key] = value
        try:
            return cls(**kwargs)
        except TypeError:
            # 单个坏字段不应让整个素材清单失败：逐字段回退
            safe: dict[str, Any] = {}
            for key, value in kwargs.items():
                try:
                    safe_obj = cls(**{key: value})
                except TypeError:
                    continue
                safe[key] = getattr(safe_obj, key)
            return cls(**safe)

    def to_dict(self, *, drop_none: bool = True) -> dict[str, Any]:
        """序列化；默认丢弃 None 字段，使写出的 library.json / 图层快照保持精简。"""
        out: dict[str, Any] = {}
        for spec in fields(self):
            value = getattr(self, spec.name)
            if value is None and drop_none:
                continue
            out[spec.name] = value
        return out


def resolve_chain(*levels: "ProductionParams | None") -> ProductionParams:
    """按「低优先级 → 高优先级」顺序合并多层参数，返回最终有效参数。

    用法（见 §5 回落链）::

        resolve_chain(product_defaults, library_defaults, material_defaults, layer_override)

    后面的层覆盖前面的层的非 None 字段。任意层可为 None。
    """
    result = ProductionParams()
    for level in levels:
        if level is not None:
            result = level.merge_onto(result)
    return result
