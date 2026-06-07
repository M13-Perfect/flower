from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLOBS = ("*.py", "tests/*.py")
EXE_PATH = PROJECT_ROOT / "dist" / "BirthFlowerMVP" / "BirthFlowerMVP.exe"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Birth Flower desktop app as a Windows exe.")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip pytest before packaging. Not recommended for release builds.",
    )
    parser.add_argument(
        "--allow-non-windows-checks",
        action="store_true",
        help="Run compile/test checks on non-Windows without attempting to build the exe.",
    )
    args = parser.parse_args()

    is_windows = platform.system() == "Windows"
    if not is_windows and not args.allow_non_windows_checks:
        print(
            "Windows exe 必须在 Windows Python 环境中打包；"
            "当前系统不是 Windows。请在 Windows 上运行此脚本，"
            "或使用 --allow-non-windows-checks 仅执行可运行性检查。",
            file=sys.stderr,
        )
        return 2

    _run_py_compile()
    if not args.skip_tests:
        _run([sys.executable, "-m", "pytest", "-q"])
    _check_tkinter()

    if not is_windows:
        print("非 Windows 环境检查已通过；跳过 exe 打包。")
        return 0

    _check_pyinstaller()
    _run([sys.executable, "-m", "PyInstaller", "--noconfirm", "BirthFlowerMVP.spec"])
    if not EXE_PATH.exists():
        raise SystemExit(f"打包结束但未找到 exe：{EXE_PATH}")
    print(f"Windows exe 已生成：{EXE_PATH}")
    return 0


def _run_py_compile() -> None:
    # 打包前先编译全部源码，提前发现语法错误，避免生成不可启动 exe。
    files: list[str] = []
    for pattern in SOURCE_GLOBS:
        files.extend(str(path.relative_to(PROJECT_ROOT)) for path in PROJECT_ROOT.glob(pattern))
    _run([sys.executable, "-m", "py_compile", *sorted(files)])


def _check_tkinter() -> None:
    # Windows 双击 exe 依赖 Tk/Tcl；这里验证当前 Python 能导入 Tkinter。
    _run([sys.executable, "-c", "import tkinter; import tkinter.ttk; print('tkinter ok')"])


def _check_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit("未安装 PyInstaller；请先运行：python -m pip install -r requirements.txt") from exc


def _run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
