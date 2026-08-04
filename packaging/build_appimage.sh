#!/usr/bin/env bash
# Build a self-contained AppImage from the same frozen bundle the .deb carries.
#
# The virtualenv this replaces could never have worked: `python3 -m venv` stamps
# an absolute shebang into every console script at creation time, pointing at a
# staging directory that no longer exists at run time, and `venv/bin/python3` was
# only a symlink to the system interpreter -- so the image contained no Python.
#
# Usage: bash packaging/build_appimage.sh [version]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${ROOT}/myimages/__init__.py")"
VERSION="${1:-${DEFAULT_VERSION}}"
STAGE="$(mktemp -d)"
APPDIR="${STAGE}/myImages.AppDir"
TOOL="${APPIMAGETOOL:-${ROOT}/appimagetool-x86_64.AppImage}"
trap 'rm -rf "${STAGE}"' EXIT

PYTHON="${PYTHON:-python3}"

echo "==> Freezing the application"
"${PYTHON}" -m PyInstaller --clean --noconfirm \
    --distpath "${STAGE}/dist" --workpath "${STAGE}/build" \
    "${ROOT}/packaging/myimages.spec"

echo "==> Staging the AppDir"
install -d "${APPDIR}/usr" "${APPDIR}/usr/share/applications" \
           "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
cp -a "${STAGE}/dist/myimages" "${APPDIR}/usr/myimages"

# AppRun resolves the bundle from its own location rather than a fixed path: an
# AppImage is mounted somewhere different on every run.
cat > "${APPDIR}/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "${HERE}/usr/myimages/myimages" "$@"
APPRUN
chmod 0755 "${APPDIR}/AppRun"

install -m 0644 "${ROOT}/packaging/myimages.desktop" "${APPDIR}/myimages.desktop"
install -m 0644 "${ROOT}/packaging/myimages.desktop" \
    "${APPDIR}/usr/share/applications/myimages.desktop"
"${PYTHON}" "${ROOT}/scripts/export_icon.py" "${APPDIR}/myimages.png" 256
cp "${APPDIR}/myimages.png" \
    "${APPDIR}/usr/share/icons/hicolor/256x256/apps/myimages.png"

if [ ! -x "${TOOL}" ]; then
  echo "==> Fetching appimagetool"
  curl -fsSL -o "${TOOL}" \
    https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "${TOOL}"
fi

echo "==> Building AppImage"
# --appimage-extract-and-run because appimagetool is itself an AppImage and CI
# runners have no FUSE; without it the build dies with "failed to set up fuse".
ARCH=x86_64 "${TOOL}" --appimage-extract-and-run \
    "${APPDIR}" "${ROOT}/myImages-${VERSION}-x86_64.AppImage"
echo "Built ${ROOT}/myImages-${VERSION}-x86_64.AppImage"
