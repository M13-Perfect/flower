# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


project_root = Path(SPECPATH)
datas = []
for relative in ("README.md", "requirements.txt", "glyph_maps/glyph_maps.json"):
    source = project_root / relative
    if source.exists():
        datas.append((str(source), str(Path(relative).parent)))

hiddenimports = [
    "glyph_panel",  # glyph panel is imported lazily from the Edit menu.
    "PIL.ImageTk",
    "PIL._tkinter_finder",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.ttk",
]


a = Analysis(
    ["birth_flower_mvp.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="BirthFlowerMVP",
)
