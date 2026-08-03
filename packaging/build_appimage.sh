#!/usr/bin/env bash
# Build a self-contained AppImage: a Python venv with myImages plus an AppRun
# entry point, packaged with appimagetool. Downloads appimagetool on first run.
#
# Usage: bash packaging/build_appimage.sh [version]
set -euo pipefail

VERSION="${1:-0.0.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPDIR="$(mktemp -d)/myImages.AppDir"
TOOL="${ROOT}/appimagetool-x86_64.AppImage"

echo "==> Staging AppDir with a virtualenv"
mkdir -p "${APPDIR}/usr/bin"
python3 -m venv "${APPDIR}/usr/venv"
"${APPDIR}/usr/venv/bin/pip" install --upgrade pip >/dev/null
"${APPDIR}/usr/venv/bin/pip" install "${ROOT}" >/dev/null

cat > "${APPDIR}/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "${HERE}/usr/venv/bin/myimages" "$@"
APPRUN
chmod +x "${APPDIR}/AppRun"

install -m 0644 "${ROOT}/packaging/myimages.desktop" "${APPDIR}/myimages.desktop"
"${APPDIR}/usr/venv/bin/python" "${ROOT}/scripts/export_icon.py" \
    "${APPDIR}/myimages.png" 256

if [ ! -x "${TOOL}" ]; then
  echo "==> Fetching appimagetool"
  curl -L -o "${TOOL}" \
    https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "${TOOL}"
fi

echo "==> Building AppImage"
ARCH=x86_64 "${TOOL}" "${APPDIR}" "${ROOT}/myImages-${VERSION}-x86_64.AppImage"
echo "Built ${ROOT}/myImages-${VERSION}-x86_64.AppImage"
rm -rf "$(dirname "${APPDIR}")"
