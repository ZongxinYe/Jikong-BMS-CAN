from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

datas = [
    (
        str(SRC / "bms_can_monitor" / "protocol" / "bms_jikong_v2_1.dbc"),
        "bms_can_monitor/protocol",
    ),
]
binaries = [
    (
        str(ROOT / "third_party" / "controlcan" / "x64" / "ControlCAN.dll"),
        "third_party/controlcan/x64",
    ),
]
hiddenimports = collect_submodules("cantools.database.can.formats")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "matplotlib",
        "PIL",
        "OpenGL",
        "pyqtgraph.opengl",
        "PySide6.QtTest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BMS-CAN-Monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BMS-CAN-Monitor",
)
