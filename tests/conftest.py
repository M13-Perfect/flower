import pytest

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - CTk 未安装时退化为无操作
    ctk = None


@pytest.fixture(autouse=True)
def _isolate_prompt_store(tmp_path_factory, monkeypatch):
    """把配置 + 共享提示词库 prompts.db 重定向到临时目录，避免污染真实机器文件。

    提示词整套已搬进与配置同目录的 SQLite 库 prompts.db；load_config 反序列化旧产品时
    会就地迁移并 save_config 一次（写盘副作用）。若不隔离，任何直接 BirthFlowerApp(root) /
    config_store 默认路径的用例都会在真实数据目录建/改 prompts.db。这里给每个用例一份干净的
    临时配置目录：
      ① DEFAULT_CONFIG_PATH 指向 tmp，使 prompts_db._default_db_path() = tmp/prompts.db；
      ② ui_app.load_config/save_config 改读写这份 tmp 配置（不动签名、不改源码默认参数）。
    显式传入自有路径的用例（如 test_config_store、_isolated_prompt_db_app）会各自覆盖，不受影响。
    """
    import config_store

    tmp_dir = tmp_path_factory.mktemp("prompt_store")
    cfg_path = tmp_dir / "birth_flower_config.json"
    config_store.save_config(config_store.AppConfig(), cfg_path)
    monkeypatch.setattr(config_store, "DEFAULT_CONFIG_PATH", cfg_path, raising=False)
    try:
        import ui_app as _ui_app
    except Exception:  # pragma: no cover - 非 UI 用例可能未触发 ui_app 导入
        _ui_app = None
    if _ui_app is not None:
        monkeypatch.setattr(_ui_app, "load_config", lambda *a, **k: config_store.load_config(cfg_path))
        monkeypatch.setattr(_ui_app, "save_config", lambda cfg, *a, **k: config_store.save_config(cfg, cfg_path))
    yield


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
