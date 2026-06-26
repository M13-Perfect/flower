# PyInstaller runtime hook —— flower 冻结态启动粘合层（macOS/.app 主要，Win onedir 同样安全）。
#
# 在任何业务模块 import 之前执行，把冻结态需要的 env/CWD 就位。支持两种打包形态：
#   1) 本地全量构建：商业资产(BirthMonth flowers/ + 字体)随包在 _MEIPASS → 资产根=_MEIPASS。
#   2) 云构建空壳：这些资产被 .gitignore、不在公开仓库 → 没随包；资产根=可写数据目录
#      (~/Library/Application Support/BirthFlower)，用户手动把 BirthMonth flowers/ 与
#      Birthmonth_font.ttf 放进去即可（见 docs/macos-build.md）。
# 全用 setdefault：开发者显式设的 env 优先，绝不覆盖。
import os
import sys

if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)

    # ── 可写数据根（配置/输出/收件夹/手动资产）。macOS .app 内部只读，必须落到用户目录 ──
    if sys.platform == "darwin":
        data_dir = os.path.expanduser("~/Library/Application Support/BirthFlower")
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        data_dir = os.path.join(appdata, "BirthFlower") if appdata else os.path.join(base, "data")
    else:
        data_dir = os.path.expanduser("~/.local/share/BirthFlower")
    try:
        os.makedirs(data_dir, exist_ok=True)
    except OSError:
        data_dir = base  # 实在建不了就退回包内（只读，功能降级但不崩）

    os.environ.setdefault("BIRTHFLOWER_DATA_DIR", data_dir)
    os.environ.setdefault("FLOWER_PY_REEXEC", "1")  # 跳过 Windows 专属 .venv-win re-exec（双保险）

    # ── 资产根：随包带了 BirthMonth flowers 就用包内（本地全量构建）；没带就用 data_dir（云空壳，用户手动放）──
    bundled = os.path.isdir(os.path.join(base, "BirthMonth flowers"))
    asset_root = base if bundled else data_dir
    os.environ.setdefault("FLOWER_PROJECT_ROOT", asset_root)  # domain 层 _project_root()/PROJECT_ROOT 命中这里

    if not bundled:
        # 云空壳：把随包的只读 json 资产首次铺进 data_dir，使 FLOWER_PROJECT_ROOT 下齐全（仅缺失时复制，
        # 保留用户对 templates 的回写，如物理尺寸）。BirthMonth flowers/ 与字体由用户自行放入 data_dir。
        import shutil
        for name in ("templates", "assets"):
            src = os.path.join(base, name)
            dst = os.path.join(data_dir, name)
            if os.path.isdir(src) and not os.path.exists(dst):
                try:
                    shutil.copytree(src, dst)
                except OSError:
                    pass

    # ── 默认素材/字体是相对路径(Path("BirthMonth flowers")/Path("Birthmonth_font.ttf"))，按 CWD 解析 ──
    # 切到资产根，让首启默认值命中（包内或 data_dir）。写盘走绝对的 BIRTHFLOWER_DATA_DIR，不受影响。
    try:
        os.chdir(asset_root)
    except OSError:
        pass
