from pathlib import Path


def test_windows_python_launcher_uses_path_python_for_entrypoint():
    entrypoint = Path("birth_flower_mvp.py")

    assert entrypoint.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/env python"
