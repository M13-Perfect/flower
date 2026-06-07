from pathlib import Path


def test_windows_pyinstaller_spec_exists_and_uses_entrypoint():
    spec = Path("BirthFlowerMVP.spec")
    text = spec.read_text(encoding="utf-8")

    assert '["birth_flower_mvp.py"]' in text
    assert 'name="BirthFlowerMVP"' in text
    assert 'console=False' in text


def test_windows_build_script_checks_before_packaging():
    script = Path("tools/build_windows_exe.py").read_text(encoding="utf-8")

    assert "py_compile" in script
    assert "pytest" in script
    assert "tkinter" in script
    assert "PyInstaller" in script


def test_requirements_include_pyinstaller_for_windows_builds():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").casefold()

    assert "pyinstaller" in requirements
