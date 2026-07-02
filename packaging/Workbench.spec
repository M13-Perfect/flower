# -*- mode: python ; coding: utf-8 -*-
"""统一打包：一个 onedir bundle，产物 dist/Workbench/app.exe（按角色 launcher/flower/ezcad/serve 运行）。

打包策略（见 packaging/app_dispatcher.py 顶部说明）：
  - **一方代码全部作为 data 装入**（srcflower/ 与 srcezcad/），运行时按角色把对应目录插到 sys.path。
    任何一方模块都不进 PYZ，故两个同名 `app` 包（services/api 与 inbox-service）永不冲突。
  - **第三方依赖**经 hiddenimports + collect_all/collect_submodules 收集进 _internal（共享一份）。
  - upx=False（遵 Ezcad PACKAGING.md：UPX 会被火绒等误报）；console=False（无黑窗）。

构建：在含「全部依赖（flower 全集 + sqlalchemy/alembic）」的 venv 里
    pyinstaller --noconfirm packaging/Workbench.spec
通常由 packaging/build_release.ps1 调用。
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH 由 PyInstaller 注入，指向本 spec 所在目录（flower/packaging）。
PACKAGING_DIR = Path(SPECPATH).resolve()
FLOWER_ROOT = PACKAGING_DIR.parent
_env_ezcad = os.environ.get("EZCAD_SRC")
EZCAD_SRC = Path(_env_ezcad).resolve() if _env_ezcad else (FLOWER_ROOT.parent / "Ezcad2.7.6").resolve()

# os.walk 期间被剪掉的目录名（任意深度匹配 basename）。
_EXCLUDE_DIRS = {
    ".git", ".venv", ".venv-win", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build", ".next",
    "coverage", "release", ".idea", ".vscode", ".claude", "tests", "__tests__",
    "sandbox", "outputs",
}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".zip", ".log"}


def _is_excluded_file(name: str) -> bool:
    low = name.lower()
    if Path(name).suffix.lower() in _EXCLUDE_SUFFIXES:
        return True
    # SQLite 伴生/备份文件后缀不是 .db（如 inbox.db-wal / inbox.db-shm / inbox.db.bak-20260619），
    # 精确后缀集匹配不到——这些含**真实客户订单数据**，必须按名字模式严防入包。
    return ".db-" in low or ".db." in low or ".sqlite-" in low or ".bak" in low


def tree(src: Path, dest_prefix: str) -> list[tuple[str, str]]:
    """把 src 下的文件（剪掉 _EXCLUDE_DIRS / *.egg-info / 排除文件）收成 (abs_file, dest_dir) 列表。"""
    out: list[tuple[str, str]] = []
    src = Path(src)
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS and not d.endswith(".egg-info")]
        rel = Path(root).relative_to(src)
        dest_dir = str(Path(dest_prefix) / rel) if str(rel) != "." else dest_prefix
        for name in files:
            if _is_excluded_file(name):
                continue
            out.append((str(Path(root) / name), dest_dir))
    return out


def globs(src: Path, pattern: str, dest_prefix: str) -> list[tuple[str, str]]:
    return [(str(p), dest_prefix) for p in Path(src).glob(pattern) if p.is_file()]


# ---- 一方代码作为 data 装入 ---------------------------------------------------
# flower 根：装运行所需的代码 + 字体/花材资源。
datas: list[tuple[str, str]] = []
datas += globs(FLOWER_ROOT, "*.py", "srcflower")                       # flower 根扁平模块（ui_app/config_store/...）
datas += tree(FLOWER_ROOT / "glyph_maps", "srcflower/glyph_maps")      # 字形映射 JSON（ui_app 需要）
# 字体/花材资源：导出端经 _project_root()/Birthmonth_font.ttf、_project_root()/'BirthMonth flowers'(业务字体)、
# _project_root()/assets/fonts 解析；缺失会 FONT_LOAD_FAILED。随包进 srcflower，launcher 首启再播种到 DATA_ROOT。
datas += globs(FLOWER_ROOT, "*.ttf", "srcflower")
datas += globs(FLOWER_ROOT, "*.otf", "srcflower")
datas += tree(FLOWER_ROOT / "BirthMonth flowers", "srcflower/BirthMonth flowers")
datas += tree(FLOWER_ROOT / "assets" / "fonts", "srcflower/assets/fonts")            # 当前可能不存在，tree 容缺
# 只收 app/ 子包：serve 只 import app.*、flower 导出只 import services/api 的 app.*。收窄到 app/ 一举排除
# 两仓根下的 .venv / inbox.db*（含真实订单数据，PII）/ *.bak / 各类缓存 / *.egg-info / tests，从根上杜绝泄密与臃肿。
datas += tree(FLOWER_ROOT / "services" / "api" / "app", "srcflower/services/api/app")
datas += tree(FLOWER_ROOT / "automation" / "inbox-service" / "app", "srcflower/automation/inbox-service/app")
# Ezcad：只装 ezcad_auto_layout 包（run_ezcad 导入它）。
datas += tree(EZCAD_SRC / "ezcad_auto_layout", "srcezcad/ezcad_auto_layout")

# ---- 第三方依赖 ---------------------------------------------------------------
binaries: list = []
hiddenimports: list[str] = [
    "launcher",  # dispatcher 惰性 import；显式列出确保被收集（含 customtkinter 依赖图）
    "PIL.ImageTk", "PIL._tkinter_finder",
    "sqlalchemy.dialects.sqlite",
    "uharfbuzz", "pyclipper", "cairosvg",
    # GUI（两端）
    "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk",
]
# 一方代码是 loose data、未被 PyInstaller 分析，故其第三方依赖必须**整树**收集：collect_submodules
# 枚举整个包的全部子模块，避免「按需子模块没被带进来」——例如 fastapi.middleware.cors（仅列顶层
# 包名时不会自动带）。这是 loose-data 打包方式的关键点。
_collect_pkgs = [
    # web/服务栈（flower 导出端 + inbox-service 共用）
    "fastapi", "starlette", "pydantic", "pydantic_core", "anyio", "click", "h11",
    "httpx", "httpcore", "uvicorn", "sqlalchemy", "alembic", "openpyxl",
    # 图形/矢量/字体栈（flower）
    "ezdxf", "fontTools", "svgwrite", "numpy", "PIL",
]
for pkg in _collect_pkgs:
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:  # noqa: BLE001 — 某依赖缺席不应阻断分析
        pass

for pkg in ("customtkinter", "freetype"):  # customtkinter 带主题 JSON；freetype-py 带原生 DLL
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001 — 某依赖缺席不应阻断分析（freetype 可能未装）
        pass


a = Analysis(
    [str(PACKAGING_DIR / "app_dispatcher.py")],
    pathex=[str(PACKAGING_DIR)],   # 只放 packaging，使 launcher 可被发现；不放 flower 根（避免一方模块进 PYZ）
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PIL.AvifImagePlugin"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Workbench",
)
