# -*- mode: python ; coding: utf-8 -*-
# flower → macOS .app PyInstaller spec。**仅在 macOS 上构建**（PyInstaller 不支持跨平台编译，
# Windows 出不了 .app）。由 .github/workflows/build-macos.yml 在 macos-latest(arm64) runner 上执行。
#
# 设计：只读资产全部铺到 _MEIPASS 根；services/api 的 `app` 顶层包靠 collect_submodules 进 PYZ；
# 冻结态路径/数据根由 runtime hook(pyi_rthook_flower.py) 注入 env 统一兜底（详见该文件与 docs/macos-build.md）。
import sys
import glob
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

PROJECT_ROOT = Path(SPECPATH).resolve()
SERVICES_API = PROJECT_ROOT / "services" / "api"
# 让 collect_submodules('app') 能定位 services/api 下的 `app` 顶层包（top_level.txt=app）。
if str(SERVICES_API) not in sys.path:
    sys.path.insert(0, str(SERVICES_API))

# ── 运行期只读资产：存在才打包（缺失不报错）──
# 注意：datas 元组是 Python 字符串，带空格目录名 "BirthMonth flowers" 直接写即可（不走命令行 --add-data，绕开空格坑）。
# 关键：BirthMonth flowers/ 与 Birthmonth_font.ttf 是被 .gitignore 排除的商业资产（公开仓库不上传），
# 云构建 runner 上不存在 → 这里**存在才加、缺失跳过**，构建照常成功；运行期由用户把这两样放进数据目录
# (~/Library/Application Support/BirthFlower)，runtime hook 会从那里解析（见 pyi_rthook_flower.py 与 docs/macos-build.md）。
# 本地全量构建（资产在）则正常随包，hook 自动切回包内解析。
_candidate_datas = [
    ("BirthMonth flowers", "BirthMonth flowers"),  # 28 花型 .svg(含尾随空格名) + Front1-4.ttf + heart.svg（商业资产，常缺）
    ("Birthmonth_font.ttf", "."),                  # 默认单文件字体源（商业资产，常缺）
    ("glyph_maps", "glyph_maps"),                  # glyph_maps.json + glyph_bindings.json + glyph_rules.json（已入库）
    ("assets", "assets"),                          # icons/*.svg + symbols/heart.svg（已入库）
    ("templates", "templates"),                    # products/birth-flower-card.json（已入库）
]
datas = [(s, d) for (s, d) in _candidate_datas if (PROJECT_ROOT / s).exists()]
_skipped = [s for (s, d) in _candidate_datas if not (PROJECT_ROOT / s).exists()]
if _skipped:
    print(f"[flower-macos.spec] 跳过未随包的资产（运行期由用户放入数据目录）: {_skipped}")

datas += collect_data_files("customtkinter")       # 主题/字体数据（set_default_color_theme("dark-blue") 必读）
try:
    datas += collect_data_files("cairosvg")        # cairo 缺失时该调用可能抛错；非核心，跳过不影响构建
except Exception as _e:
    print(f"[flower-macos.spec] cairosvg 数据收集跳过（PNG/图标栅格化将降级）: {_e}")

# ── hiddenimports：tkinter 全家桶 + 惰性/动态 import 目标 + services/api 的 app 包 ──
hiddenimports = [
    "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk",
    "PIL.ImageTk", "PIL._tkinter_finder",
    "glyph_panel",            # 从「编辑」菜单惰性 import
    "ezdxf", "cairosvg",      # 经 importlib 字符串导入（dxf.py / png.py），静态扫不到
]
hiddenimports += collect_submodules("app")          # services/api 的 app 包（核心；需上面 sys.path 已含 services/api）
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("cairosvg")
hiddenimports += collect_submodules("fontTools")
hiddenimports += collect_submodules("ezdxf")
hiddenimports += collect_submodules("openpyxl")
hiddenimports += collect_submodules("pydantic")
# 关键叶子兜底（防 collect_submodules 个别漏收）：
hiddenimports += [
    "app", "app.domain",
    "app.domain.exports.dxf", "app.domain.exports.svg", "app.domain.exports.png",
    "app.domain.orders.batch_generate", "app.domain.orders.batch_import",
    "app.domain.orders.batch_store",
    "app.domain.templates.physical", "app.domain.templates.engine",
    "app.domain.fonts.scanner", "app.domain.fonts.options",
    "app.domain.settings", "app.domain.output_store.store",
]

# ── 原生库：cairosvg 运行期 dlopen libcairo（wheel 不含）+ freetype-py ──
binaries = []
binaries += collect_dynamic_libs("cairocffi")
binaries += collect_dynamic_libs("freetype")
if sys.platform == "darwin":
    # 把 brew 的 libcairo 及其依赖链显式收进包（cairocffi 旁通常没有 dylib，collect_dynamic_libs 抓不到）。
    for brew_lib in ("/opt/homebrew/lib", "/usr/local/lib"):  # arm64 / intel 两种 brew 前缀
        if Path(brew_lib).is_dir():
            for pat in ("libcairo.2.dylib", "libpixman-1*.dylib", "libfontconfig*.dylib",
                        "libfreetype*.dylib", "libpng16*.dylib", "libglib-2.0*.dylib", "libffi*.dylib"):
                for f in glob.glob(f"{brew_lib}/{pat}"):
                    binaries.append((f, "."))
            break

a = Analysis(
    ["birth_flower_mvp.py"],
    pathex=[str(PROJECT_ROOT), str(SERVICES_API)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rthook_flower.py"],   # 冻结态 env/CWD 注入（见文件头）
    excludes=["pytest", "tests"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BirthFlowerMVP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # macOS 上 UPX 破坏 dylib/代码签名，必须关
    console=False,             # 窗口程序（= --windowed），不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,          # 跟随构建机/ runner 架构（macos-latest = arm64）
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
    name="BirthFlowerMVP",
)
app = BUNDLE(
    coll,
    name="BirthFlowerMVP.app",
    icon=None,                 # 暂无 .icns，用系统默认图标（不影响运行；后续可补品牌图标）
    bundle_identifier="com.flower.birthflowermvp",
    info_plist={
        "CFBundleName": "BirthFlowerMVP",
        "CFBundleDisplayName": "Birth Flower MVP",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,          # Retina（否则字糊）
        "LSMinimumSystemVersion": "11.0",
        "NSRequiresAquaSystemAppearance": False,  # 允许深色外观（CTk 深色主题）
        "LSApplicationCategoryType": "public.app-category.graphics-design",
    },
)
