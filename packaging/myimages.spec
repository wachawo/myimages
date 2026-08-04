# PyInstaller spec shared by every artifact: the Debian package, the AppImage
# and the Windows zip all bundle the tree this produces.
#
# The virtualenv approach it replaces could not work. `python3 -m venv` stamps
# an absolute shebang into every console script at creation time, pointing at
# the staging directory the build script deletes on its last line, and
# `venv/bin/python3` is only a symlink to the system interpreter -- so the
# artifacts contained no Python at all and their launcher died with "bad
# interpreter". A frozen bundle carries its own interpreter and has no shebangs.
#
# onedir rather than onefile: it starts faster, it trips far fewer antivirus
# heuristics on Windows, and every binary inside can be signed individually if
# that ever happens.
#
# Build with:  pyinstaller --clean --noconfirm packaging/myimages.spec

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

SPEC_DIR = Path(SPECPATH).resolve()
PROJECT = SPEC_DIR.parent
MACOS = sys.platform == "darwin"

# The macOS build renders this before invoking PyInstaller, because iconutil
# only exists there. Absent on every other platform, and absent on a bare
# `pyinstaller packaging/myimages.spec` run, which stays valid.
ICNS = SPEC_DIR / "myimages.icns"

# The optional segmentation runtime is vendored so background removal works in a
# packaged build. It has to be: `sys.executable -m pip` inside a bundle launches
# a second copy of the application rather than installing anything, and the
# prefix is read-only or root-owned besides. The weights are NOT bundled -- they
# are 170 MiB that most users never need, and they are fetched at first use into
# the user's own data directory, which is writable in every deployment.
VERSION = re.search(
    r'^__version__ = "(.*)"$',
    (PROJECT / "myimages" / "__init__.py").read_text(),
    re.M,
).group(1)

try:
    import onnxruntime  # noqa: F401

    ONNX_BINARIES = collect_dynamic_libs("onnxruntime")
    ONNX_HIDDEN = ["onnxruntime", "onnxruntime.capi.onnxruntime_pybind11_state"]
except ImportError:  # pragma: no cover - a core-only build is still valid
    ONNX_BINARIES = []
    ONNX_HIDDEN = []

# Bundled viewer plugins are ordinary modules now rather than files discovered
# by a directory scan, so naming them here is all it takes for the frozen build
# to find them.
HIDDEN = [
    "myimages.plugins.three_d_preview",
    *ONNX_HIDDEN,
]

# Qt ships far more than this app uses. Dropping the modules it never imports
# takes roughly a third off the bundle and, more usefully, removes whole
# categories of missing-system-library failure at start-up.
EXCLUDED = [
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "tkinter",
]

analysis = Analysis(
    [str(PROJECT / "main.py")],
    pathex=[str(PROJECT)],
    binaries=ONNX_BINARIES,
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="myimages",
    debug=False,
    strip=False,
    upx=False,
    # Windowed on Windows and macOS so no console appears behind the window.
    # Left as a console binary on Linux, where the launcher is run from a
    # desktop entry and Ctrl+C in a terminal is a documented way to quit.
    console=not sys.platform.startswith(("win", "darwin")),
)

collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="myimages",
)

if MACOS:
    # A .app bundle, not a bare directory: Finder will not launch a folder, and
    # the Dock, the application menu and the window title all read this plist.
    #
    # Left ad-hoc signed, which is what PyInstaller does when given no identity.
    # That is not cosmetic on Apple Silicon: an unsigned Mach-O will not execute
    # there at all. It is still not a Developer ID signature, so Gatekeeper will
    # quarantine a downloaded copy -- the README says how to clear it.
    BUNDLE(
        collected,
        name="myImages.app",
        icon=str(ICNS) if ICNS.is_file() else None,
        bundle_identifier="com.wachawo.myimages",
        version=VERSION,
        info_plist={
            "CFBundleName": "myImages",
            "CFBundleDisplayName": "myImages",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            # Without this the window is drawn at 1x and scaled up, which on a
            # Retina display looks like a rendering fault rather than a choice.
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.photography",
            "NSHumanReadableCopyright": "MIT licensed",
        },
    )
