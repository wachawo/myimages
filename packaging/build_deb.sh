#!/usr/bin/env bash
# Build a .deb that installs myImages into /opt/myimages.
#
# The package carries a frozen bundle rather than a virtualenv. The virtualenv it
# replaces could never have worked: `python3 -m venv` stamps an absolute shebang
# into every console script at creation time, pointing at the staging directory
# this script deletes on its last line, and `venv/bin/python3` is only a symlink
# to the system interpreter -- so the package contained no Python at all and
# /usr/bin/myimages died with "bad interpreter".
#
# Usage: bash packaging/build_deb.sh [version]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The version lives in one place; read it rather than repeating it here.
DEFAULT_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${ROOT}/myimages/__init__.py")"
VERSION="${1:-${DEFAULT_VERSION}}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
STAGE="$(mktemp -d)"
PKG="myimages_${VERSION}_${ARCH}"
trap 'rm -rf "${STAGE}"' EXIT

PYTHON="${PYTHON:-python3}"

echo "==> Freezing the application"
"${PYTHON}" -m PyInstaller --clean --noconfirm \
    --distpath "${STAGE}/dist" --workpath "${STAGE}/build" \
    "${ROOT}/packaging/myimages.spec"

echo "==> Staging the package tree"
install -d "${STAGE}/${PKG}/opt" \
           "${STAGE}/${PKG}/usr/bin" \
           "${STAGE}/${PKG}/usr/share/applications" \
           "${STAGE}/${PKG}/usr/share/icons/hicolor/256x256/apps"
cp -a "${STAGE}/dist/myimages" "${STAGE}/${PKG}/opt/myimages"

# A launcher rather than a symlink: the bundle resolves its own libraries from
# the real executable's directory, and a shell wrapper keeps that unambiguous.
cat > "${STAGE}/${PKG}/usr/bin/myimages" <<'LAUNCH'
#!/bin/sh
exec /opt/myimages/myimages "$@"
LAUNCH
chmod 0755 "${STAGE}/${PKG}/usr/bin/myimages"

install -m 0644 "${ROOT}/packaging/myimages.desktop" \
    "${STAGE}/${PKG}/usr/share/applications/myimages.desktop"
# Rendered through the interpreter that built the bundle, not the frozen binary:
# the frozen one takes no script argument.
"${PYTHON}" "${ROOT}/scripts/export_icon.py" \
    "${STAGE}/${PKG}/usr/share/icons/hicolor/256x256/apps/myimages.png" 256

echo "==> Control metadata"
install -d "${STAGE}/${PKG}/DEBIAN"
INSTALLED_KB="$(du -sk "${STAGE}/${PKG}" | cut -f1)"
# Qt links these at load time and the bundle cannot carry them: they pull in the
# graphics stack of the host. This is the same set CI installs before the test
# suite can import QtGui at all. The t64 alternative covers Ubuntu 24.04, where
# the 64-bit time_t transition renamed the glib package.
cat > "${STAGE}/${PKG}/DEBIAN/control" <<CONTROL
Package: myimages
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: ${ARCH}
Installed-Size: ${INSTALLED_KB}
Depends: libc6, libegl1, libgl1, libglib2.0-0 | libglib2.0-0t64, libdbus-1-3, libxkbcommon0, libfontconfig1, libfreetype6
Recommends: ffmpeg
Maintainer: Aleksandr <wachawo@gmail.com>
Description: Lightweight photo and video viewer, editor and converter
 View photos and videos with thumbnails, crop and convert images, remove a
 background by hand or with a model, combine images into a size-controlled PDF,
 find duplicates, batch rename and export GIFs. Extensible through plugins.
 .
 The package carries its own Python runtime, so no system Python is required.
CONTROL

echo "==> Building package"
dpkg-deb --build --root-owner-group "${STAGE}/${PKG}" "${ROOT}/${PKG}.deb"
echo "Built ${ROOT}/${PKG}.deb"
