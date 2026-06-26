# PyInstaller runtime hook —— flower 冻结态启动粘合层（macOS/.app 主要，Win onedir 同样安全）。
#
# 在任何业务模块 import 之前执行，把冻结态需要的 env/CWD 就位，使：
#   1) services/api 域层的 _project_root()/PROJECT_ROOT（都优先读 FLOWER_PROJECT_ROOT）命中随包只读资产根；
#   2) config_store._data_root()（优先读 BIRTHFLOWER_DATA_DIR）把配置/输出写到用户可写目录；
#   3) 默认素材库相对路径 Path("BirthMonth flowers") 在双击启动（CWD=/）时仍能解析到随包资源。
# 全用 setdefault：开发者显式设的 env 优先，绝不覆盖。
import os
import sys

if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)

    # 1) 只读资产根：domain 层所有 _project_root()/PROJECT_ROOT 优先读它。
    os.environ.setdefault("FLOWER_PROJECT_ROOT", base)

    # 2) 跳过 Windows 专属的 .venv-win re-exec（双保险；ui_app 本身已有 sys.frozen 守卫）。
    os.environ.setdefault("FLOWER_PY_REEXEC", "1")

    # 3) 可写数据根（配置/输出/收件夹）。macOS .app 内部只读，必须落到用户目录。
    if sys.platform == "darwin":
        data_dir = os.path.expanduser("~/Library/Application Support/BirthFlower")
    elif os.name == "nt":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        data_dir = os.path.join(appdata, "BirthFlower") if appdata else os.path.join(base, "data")
    else:
        data_dir = os.path.expanduser("~/.local/share/BirthFlower")
    try:
        os.makedirs(data_dir, exist_ok=True)
        os.environ.setdefault("BIRTHFLOWER_DATA_DIR", data_dir)
    except OSError:
        pass  # 建不了就让 config_store 走它自己的冻结态兜底逻辑

    # 4) 默认素材/字体是相对路径，按 CWD 解析；双击 .app 时 CWD=/ → 素材库空。
    #    把 CWD 切到随包资源根，让首启默认值命中。写盘仍走上面的绝对 BIRTHFLOWER_DATA_DIR。
    try:
        os.chdir(base)
    except OSError:
        pass
