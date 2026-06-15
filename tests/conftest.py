import pytest

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - CTk 未安装时退化为无操作
    ctk = None


@pytest.fixture(autouse=True)
def _cleanup_customtkinter_trackers():
    """每个用例后清理 CustomTkinter 全局 tracker。

    CTk 用全局 ScalingTracker/AppearanceModeTracker 记录每个窗口；测试反复
    create/destroy Tk root 会残留已销毁窗口的引用，后续用例创建 CTk 控件时
    update_scaling_callbacks_all() 触到死引用抛 TclError（用例单跑通过、合跑报错即此因）。
    每个用例后清掉这些容器即可，不动 appearance_mode 等全局设置。
    """
    yield
    if ctk is None:
        return
    scaling = getattr(ctk, "ScalingTracker", None)
    if scaling is not None:
        getattr(scaling, "window_widgets_dict", {}).clear()
        getattr(scaling, "window_dpi_scaling_dict", {}).clear()
    appearance = getattr(ctk, "AppearanceModeTracker", None)
    if appearance is not None:
        getattr(appearance, "callback_list", []).clear()
        getattr(appearance, "app_list", []).clear()
