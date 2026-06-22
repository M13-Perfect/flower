"""统一入口（dispatcher）：一个可执行文件按角色启动三端 + 总启动器。

    app.exe [launcher|flower|ezcad|serve]

为什么按角色拉**独立子进程**、而不是同进程函数调用（见打包计划）：
  1. `services/api/app` 与 `automation/inbox-service/app` 是**两个同名顶层 `app` 包**，
     同一进程的 `sys.path` 只能让其中一个可导入；
  2. flower `ui_app.py` 模块顶层会 `ctk.set_appearance_mode("dark")`，是 CustomTkinter 全局态，
     与 Ezcad 的默认主题会相互污染；
  3. 两端各建自己的 `ctk.CTk()` root，同进程双 root 易触发 Tcl 解释器冲突。
因此 launcher 用 `subprocess.Popen(self_command(role))` 把每个角色拉成干净的子进程：
`serve` 进程只把 inbox-service 目录加进 path（`app` = inbox 的 app），`flower` 进程只把
services/api 加进 path（`app` = 导出端的 app），`ezcad` 进程只加 ezcad 源——三者永不同时。

打包形态（见 Workbench.spec）：**一方代码全部作为 data 装入**，运行时按角色把对应目录插到
`sys.path` 最前；第三方依赖由 PyInstaller 经 hiddenimports/collect_all 收集进 `_internal`。
这样任何一方模块都不进 PYZ，loose 源码靠 sys.path 干净导入，彻底规避同名包冲突。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _bundle_dir() -> Path:
    """冻结态：PyInstaller 解包根（_MEIPASS / _internal）。源码态：本文件所在目录。"""
    return Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))


def resolve_roots() -> dict[str, Path]:
    """解析四套一方代码根（源码态与冻结态各一套约定）。

    flower 仓本身就含 `services/api` 与 `automation/inbox-service`，故只需 flower 根 + Ezcad 源两处。
    """
    if _is_frozen():
        base = _bundle_dir()
        flower_root = base / "srcflower"
        ezcad_src = base / "srcezcad"
    else:
        # 源码态：本文件在 flower/packaging/ 下。
        flower_root = Path(__file__).resolve().parent.parent
        env_ezcad = os.environ.get("EZCAD_SRC")
        ezcad_src = Path(env_ezcad) if env_ezcad else flower_root.parent / "Ezcad2.7.6"
    return {
        "flower_root": flower_root,
        "services_api": flower_root / "services" / "api",
        "inbox_svc": flower_root / "automation" / "inbox-service",
        "ezcad_src": ezcad_src,
    }


def _prepend_syspath(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def self_command(role: str) -> list[str]:
    """构造「以某角色重新调用自己」的命令行（launcher 拉子进程用）。"""
    if _is_frozen():
        return [sys.executable, role]
    return [sys.executable, str(Path(__file__).resolve()), role]


# ---- 三个角色 ----------------------------------------------------------------

def run_serve() -> int:
    """inbox-service 后台服务：复刻 inbox-service/app/main.py（create_app + 两后台线程 + uvicorn）。

    只把 inbox-service 目录加进 path → 进程内 `app` = inbox 的 app（不引入 services/api 的同名包）。
    所有数据/端口路径由环境变量决定（settings_from_env），launcher 已注入指向 DATA_ROOT。
    """
    roots = resolve_roots()
    _prepend_syspath(roots["inbox_svc"])

    import threading

    import uvicorn

    from app.config import settings_from_env  # type: ignore[import-not-found]
    from app.factory import create_app  # type: ignore[import-not-found]

    settings = settings_from_env()
    # 全新门店的 DATA_ROOT 尚不存在；SQLite 无法在缺失目录下建库，故先建好（生产 .bat 旧流程
    # 因在已存在目录下跑而从未暴露此问题）。create_app→init_db 之前必须保证这些目录存在。
    for directory in (settings.db_path.parent, settings.inbox_dir, settings.reports_dir, settings.batches_dir):
        directory.mkdir(parents=True, exist_ok=True)
    application = create_app(settings)
    # 与 main.py 一致：仅生产入口起后台线程（create_app 本身不起，保测试纯净）。
    threading.Thread(target=application.state.report_watcher.run_forever, daemon=True).start()
    threading.Thread(target=application.state.refund_scheduler.run_forever, daemon=True).start()
    uvicorn.run(application, host=settings.host, port=settings.port, log_level="warning")
    return 0


def run_flower() -> int:
    """开花桌面端：services/api（导出端 app）+ flower 根模块都上 path，再 `from ui_app import main`。"""
    roots = resolve_roots()
    services_api = roots["services_api"]
    if not (services_api / "app").is_dir():
        raise SystemExit(f"未找到 services/api: {services_api}")
    _prepend_syspath(services_api)
    _prepend_syspath(roots["flower_root"])

    from ui_app import main  # type: ignore[import-not-found]

    main()
    return 0


def run_ezcad() -> int:
    """扫码导入端：复刻 Ezcad2.7.6/main.py（CTk root + AutoLayoutApp）。"""
    roots = resolve_roots()
    ezcad_src = roots["ezcad_src"]
    if not (ezcad_src / "ezcad_auto_layout").is_dir():
        raise SystemExit(
            f"未找到 Ezcad 源: {ezcad_src}\n"
            "请设环境变量 EZCAD_SRC 指向 Ezcad2.7.6 目录，或把它放在 flower 仓的同级目录。"
        )
    _prepend_syspath(ezcad_src)

    import customtkinter as ctk

    from ezcad_auto_layout.app import AutoLayoutApp  # type: ignore[import-not-found]

    root = ctk.CTk()
    root.geometry("390x380")
    AutoLayoutApp(root)
    root.mainloop()
    return 0


def run_check() -> int:
    """导入自检（不开 GUI），用退出码表示成败：`check <flower|ezcad|serve>`。

    用于冻结态验证：windowed exe 崩溃只弹对话框、难以判定，故提供一个只做导入、立即退出的角色，
    让打包后能用退出码确定性地确认各角色的导入路径（含两个同名 app 包的隔离）在 _internal 里成立。
    """
    target = sys.argv[2] if len(sys.argv) > 2 else ""
    roots = resolve_roots()
    if target == "flower":
        _prepend_syspath(roots["services_api"])
        _prepend_syspath(roots["flower_root"])
        import ui_app  # type: ignore[import-not-found]
        import app.domain.exports.dxf  # noqa: F401  # 导出端 app（确认解析到 services/api/app）
        assert callable(ui_app.main)
    elif target == "ezcad":
        _prepend_syspath(roots["ezcad_src"])
        from ezcad_auto_layout.app import AutoLayoutApp  # type: ignore[import-not-found]
        assert AutoLayoutApp is not None
    elif target == "serve":
        _prepend_syspath(roots["inbox_svc"])
        from app.factory import create_app  # type: ignore[import-not-found]
        assert callable(create_app)
    else:
        print("check 需指定角色: flower | ezcad | serve", file=sys.stderr)
        return 2
    return 0


def run_launcher() -> int:
    """总启动器。惰性 import launcher（含 customtkinter），使 serve/flower/ezcad 角色不被迫拖入 ctk。

    PyInstaller 仍能从此处的函数内 import 静态发现 launcher 并连带收集 customtkinter。
    """
    from launcher import run

    return run()


# ---- 调度 --------------------------------------------------------------------

_ROLES = {
    "serve": run_serve,
    "flower": run_flower,
    "ezcad": run_ezcad,
    "launcher": run_launcher,
    "check": run_check,
}


def _guard_std_streams() -> None:
    """windowed exe（console=False）下 sys.stdout/stderr 为 None；任何向其写入或调 isatty() 的库都会崩
    （如 uvicorn 日志格式化器）。统一兜底重定向到 devnull。源码态非 None，本函数为空操作。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    _guard_std_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    role = args[0] if args else "launcher"
    handler = _ROLES.get(role)
    if handler is None:
        print(
            f"未知角色: {role!r}；可用: {', '.join(_ROLES)}（缺省 launcher）",
            file=sys.stderr,
        )
        return 2
    try:
        return handler() or 0
    except BaseException:
        # windowed exe（console=False）会吞掉 traceback；落盘一份供排障（生产/打包验证都用得上）。
        import tempfile
        import traceback

        log = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "workbench-crash.log"
        try:
            log.write_text(f"role={role}\nargv={sys.argv}\n\n{traceback.format_exc()}", encoding="utf-8")
        except OSError:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
