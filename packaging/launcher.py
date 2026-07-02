"""总启动器（生产工作台）：双击它 → 后台拉起 inbox-service → 两个按钮开两端。

职责（见打包计划 Phase 4）：
  - 算出统一数据根 DATA_ROOT（exe 同级 data/ 目录，不可写回落 %APPDATA%/BirthFlower）；
  - 把 DATA_ROOT 翻译成子进程环境变量（FLOWER_INBOX_* / BIRTHFLOWER_DATA_DIR），保证三端读写同一处数据；
  - 后台 `serve`（无控制台黑窗），轮询 /healthz 显示「运行中 / 未连接」；
  - 「开花桌面」「扫码导入」两个按钮各拉一个干净子进程；
  - 服务起不来只标红、不阻断按钮（多门店容错）。

本模块**自包含**：只依赖标准库 + customtkinter，不 import app_dispatcher（避免循环导入），
自行推导「以某角色重新调用自己」的命令行。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib import error, request

import customtkinter as ctk

PORT = os.environ.get("FLOWER_INBOX_PORT", "8770")
HEALTH_URL = f"http://127.0.0.1:{PORT}/healthz"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 仅 Windows；其它平台为 0


# ---- 路径与环境 --------------------------------------------------------------

def _is_writable(directory: Path) -> bool:
    try:
        probe = directory / ".bf_write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_root() -> Path:
    """统一数据根。优先级：BIRTHFLOWER_DATA_DIR > 冻结态(exe 同级 data / %APPDATA%) > 源码态(flower 仓根)。

    与 flower/config_store.py 的 _data_root() 保持一致，确保 launcher 与 flower 子进程算出同一处。
    """
    env_dir = os.environ.get("BIRTHFLOWER_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if _is_writable(exe_dir):
            return exe_dir / "data"
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return (Path(appdata) if appdata else exe_dir) / "BirthFlower"
    # 源码态：用 flower 仓根（launcher.py 在 flower/packaging/ 下），复用现有 outputs/ 与配置位置。
    return Path(__file__).resolve().parent.parent


def child_env(root: Path) -> dict[str, str]:
    """把 DATA_ROOT 翻译成子进程环境变量，使三端读写同一处。

    - inbox-service 读 FLOWER_INBOX_*；flower 自身配置读 BIRTHFLOWER_DATA_DIR；
    - **FLOWER_PROJECT_ROOT**：services/api 导出端用它当「资源根 + 输出根」（_project_root()）——
      指向 DATA_ROOT 后，批量报告落 DATA_ROOT/outputs/reports（与 FLOWER_REPORTS_DIR 一致，inbox 的
      ReportWatcher 才能消费到，退款/状态回写链路才通），字体也在 DATA_ROOT 下找（见 seed_resources）。
    """
    outputs = root / "outputs"
    env = dict(os.environ)
    env["FLOWER_INBOX_HOST"] = "127.0.0.1"
    env["FLOWER_INBOX_PORT"] = PORT
    env["FLOWER_INBOX_DB"] = str(root / "inbox.db")
    env["FLOWER_INBOX_DIR"] = str(outputs / "inbox")
    env["FLOWER_REPORTS_DIR"] = str(outputs / "reports")
    env["FLOWER_BATCHES_DIR"] = str(outputs / "inbox-batches")
    env["BIRTHFLOWER_DATA_DIR"] = str(root)
    env["FLOWER_PROJECT_ROOT"] = str(root)
    return env


def seed_resources(root: Path) -> None:
    """首启把 bundle 内的字体/花材资源播种到 DATA_ROOT。

    FLOWER_PROJECT_ROOT 指向 DATA_ROOT，导出端在 _project_root()(=DATA_ROOT)/Birthmonth_font.ttf、
    /'BirthMonth flowers'、/assets/fonts 下找字体；这些资源打包在 _internal/srcflower 里，需播种过去。
    **已存在则不覆盖**（保留门店自加的字体/花材）。源码态无 _MEIPASS（资源已在 flower 仓根），跳过。
    """
    mei = getattr(sys, "_MEIPASS", None)
    if not mei:
        return
    src = Path(mei) / "srcflower"
    if not src.is_dir():
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        for font in list(src.glob("*.ttf")) + list(src.glob("*.otf")):
            dest = root / font.name
            if not dest.exists():
                shutil.copy2(font, dest)
        for name in ("BirthMonth flowers", "assets"):
            s = src / name
            d = root / name
            if s.is_dir() and not d.exists():
                shutil.copytree(s, d)
    except OSError:
        pass


def self_command(role: str) -> list[str]:
    """「以某角色重新调用自己」。冻结态 = app.exe role；源码态 = python app_dispatcher.py role。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, role]
    dispatcher = Path(__file__).resolve().parent / "app_dispatcher.py"
    return [sys.executable, str(dispatcher), role]


def _health_ok(timeout: float = 2.0) -> bool:
    try:
        with request.urlopen(HEALTH_URL, timeout=timeout) as resp:  # noqa: S310 (本机 http)
            return 200 <= resp.status < 300
    except (error.URLError, OSError, ValueError):
        return False


# ---- UI ----------------------------------------------------------------------

class LauncherApp:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.data_root = data_root()
        seed_resources(self.data_root)  # 首启把字体/花材播种到 DATA_ROOT（FLOWER_PROJECT_ROOT 指向此）
        self.env = child_env(self.data_root)
        self._serve_proc: subprocess.Popen | None = None
        self._stop = threading.Event()

        root.title("生产工作台")
        root.geometry("380x320")
        root.minsize(360, 300)

        title = ctk.CTkLabel(root, text="生产工作台", font=ctk.CTkFont(size=20, weight="bold"))
        title.pack(pady=(22, 4))

        self.status = ctk.CTkLabel(root, text="● inbox 服务  正在启动…", text_color="#e0b04a")
        self.status.pack(pady=(0, 16))

        btn_flower = ctk.CTkButton(
            root, text="🌸  开花桌面", height=52, font=ctk.CTkFont(size=15),
            command=lambda: self._spawn("flower"),
        )
        btn_flower.pack(fill="x", padx=36, pady=6)

        btn_ezcad = ctk.CTkButton(
            root, text="🔫  扫码导入", height=52, font=ctk.CTkFont(size=15),
            command=lambda: self._spawn("ezcad"),
        )
        btn_ezcad.pack(fill="x", padx=36, pady=6)

        hint = ctk.CTkLabel(
            root, text=f"数据目录：{self.data_root}", text_color="#9aa0a6",
            font=ctk.CTkFont(size=11), wraplength=320,
        )
        hint.pack(side="bottom", pady=10)

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_serve()
        self._poll_thread = threading.Thread(target=self._poll_health, daemon=True)
        self._poll_thread.start()

    def _start_serve(self) -> None:
        # 服务已在别处起（端口通）则不重复拉起。
        if _health_ok(timeout=0.6):
            return
        try:
            self._serve_proc = subprocess.Popen(
                self_command("serve"), env=self.env, creationflags=_NO_WINDOW,
            )
        except OSError as exc:  # 拉起失败不致命：按钮仍可用，状态标红。
            self._set_status(f"● inbox 服务  启动失败：{exc}", "#e05a5a")

    def _poll_health(self) -> None:
        while not self._stop.is_set():
            ok = _health_ok()
            if ok:
                self._set_status(f"● inbox 服务  :{PORT} 运行中", "#46c46a")
            else:
                self._set_status("● inbox 服务  未连接（重试中）", "#e0b04a")
            self._stop.wait(2.0)

    def _set_status(self, text: str, color: str) -> None:
        # 后台线程经 after 切回 UI 线程更新。
        self.root.after(0, lambda: self.status.configure(text=text, text_color=color))

    def _spawn(self, role: str) -> None:
        try:
            subprocess.Popen(self_command(role), env=self.env)
        except OSError as exc:
            self._set_status(f"● 启动 {role} 失败：{exc}", "#e05a5a")

    def _on_close(self) -> None:
        self._stop.set()
        if self._serve_proc and self._serve_proc.poll() is None:
            self._serve_proc.terminate()
        self.root.destroy()


def run() -> int:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    root = ctk.CTk()
    LauncherApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
