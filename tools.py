"""工具（Tool）注册表（Layer System v2 · Packet 6 · §9 / ADR）。

**工具 ≠ 内容提供器**（RFC §9 硬要求）：
- ``ContentProvider``（``providers.py``）：数据、测量、渲染、属性声明。
- ``Tool``（本模块）：指针、键盘、光标、选区、画布交互。

现状交互内联在 ``ui_app`` 的 ``_on_canvas_press/drag/release/double_click`` 与
``_start_inline_text_edit`` 里。本 Packet **只把它收口为两个可注册的工具对象**
（``SelectTool`` / ``TextTool``），**不重写、不搬运、不改交互手感**——每个工具方法都
**委托回 App 上的现有方法**（与 Packet 3 的 provider 委托同构）。

接线策略（**thin-registry，低风险**）：画布事件绑定**保持原样**（``ui_app`` 仍直接
``bind`` 到 ``_on_canvas_*``），本模块只是把交互**形式化**为可注册的对象，供未来工具
（沿路径文字 / 竖排 等）注册扩展。不路由现有绑定、不引入分发层 → 零回归风险，同时满足
「交互收口为 SelectTool + TextTool」。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 仅类型标注；避免运行时把重模块（models/ui_app）拖进来。
    from models import Layer


class Tool:
    """画布交互工具薄基类。

    ``ctx`` 约定携带 ``{'app': BirthFlowerApp, ...}``，工具方法据此委托回 App 现有交互
    方法。基类默认全部 no-op，子类只覆写自己关心的事件（与 Tk 的「不绑定即不消费」一致）。
    """

    tool_id: str = ""

    def on_press(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return None

    def on_drag(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return None

    def on_release(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return None

    def on_double_click(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return None

    def cursor(self) -> str:
        """该工具的默认光标（Tk cursor 名）。空串 = 平台默认箭头（= 当前行为）。"""
        return ""

    def activates_for(self, layer: "Layer | None") -> bool:
        """该工具是否对给定图层激活其专属能力（如 TextTool 仅对 TextLayer 内联编辑）。"""
        return True


class SelectTool(Tool):
    """选择 / 移动 / 缩放 / 平移工具：收口现有 ``_on_canvas_press/drag/release``。

    把当前隐式的 ``_drag_mode`` ∈ {move,resize,pan} 交互**整体委托**给 App 的现有方法，
    一字不改交互逻辑（手感不变）。这是「单击选中 + 拖动变换」的变换模式（§9）。
    """

    tool_id = "select"

    def on_press(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return ctx["app"]._on_canvas_press(event)

    def on_drag(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return ctx["app"]._on_canvas_drag(event)

    def on_release(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return ctx["app"]._on_canvas_release(event)

    def cursor(self) -> str:
        # 当前默认（箭头）；resize/pan 时由 _on_canvas_press 内部临时设 fleur，保持原行为。
        return ""


class TextTool(Tool):
    """文字编辑工具：收口现有内联编辑（双击进编辑 / 内联编辑器）。

    委托 ``_on_canvas_double_click``（命中 TextLayer → 进编辑）与
    ``_start_inline_text_edit``。仅对 ``TextLayer`` 激活（``activates_for``），这是
    「双击进编辑」的编辑模式（§9）。
    """

    tool_id = "text"

    def on_double_click(self, event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        return ctx["app"]._on_canvas_double_click(event)

    def start_inline_edit(self, layer_or_event: Any, ctx: dict[str, Any]) -> Any:  # noqa: ANN401
        """进入画布内联文字编辑；委托 App 现有 ``_start_inline_text_edit``。"""
        return ctx["app"]._start_inline_text_edit(layer_or_event)

    def cursor(self) -> str:
        return "xterm"

    def activates_for(self, layer: "Layer | None") -> bool:
        # 延迟 import 避免运行时 import 环；只对 TextLayer 激活内联编辑。
        from models import TextLayer

        return isinstance(layer, TextLayer)


# --- 模块级注册表（懒版：一个 dict，不造工厂/插件加载器，与 providers 同构）---
TOOLS: dict[str, Tool] = {}
_ACTIVE_TOOL_ID = "select"


def register_tool(tool: Tool) -> None:
    """登记工具，键 = tool.tool_id。新工具（沿路径/竖排）= 注册 1 个 Tool。"""
    TOOLS[tool.tool_id] = tool


def get_tool(tool_id: str) -> Tool | None:
    """按 id 查工具；未注册返回 None。"""
    return TOOLS.get(tool_id)


def active_tool() -> Tool | None:
    """当前活动工具（默认 SelectTool）。当前画布绑定不经此路由，仅为未来工具切换预留。"""
    return TOOLS.get(_ACTIVE_TOOL_ID)


def set_active_tool(tool_id: str) -> bool:
    """切换活动工具；id 未注册时不切换并返回 False。"""
    global _ACTIVE_TOOL_ID
    if tool_id not in TOOLS:
        return False
    _ACTIVE_TOOL_ID = tool_id
    return True


# 导入时注册两个工具（懒版：模块级副作用，import tools 即生效）。
register_tool(SelectTool())
register_tool(TextTool())
