#!/usr/bin/env bash
# Build a .deb that installs myImages into /opt/myimages with its own virtualenv.
# The heavy runtime (PySide6, Pillow) is vendored so the package is self-contained;
# ffmpeg stays a Recommends so users can add it via apt when they want video tools.
#
# Usage: bash packaging/build_deb.sh [version]
set -euo pipefail

VERSION="${1:-0.0.1}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
PKG="myimages_${VERSION}_${ARCH}"
INSTALL_DIR="${STAGE}/${PKG}/opt/myimages"

echo "==> Staging virtualenv"
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip >/dev/null
"${INSTALL_DIR}/venv/bin/pip" install "${ROOT}" >/dev/null

echo "==> Launcher and desktop integration"
mkdir -p "${STAGE}/${PKG}/usr/bin" \
         "${STAGE}/${PKG}/usr/share/applications" \
         "${STAGE}/${PKG}/usr/share/icons/hicolor/256x256/apps"
cat > "${STAGE}/${PKG}/usr/bin/myimages" <<'LAUNCH'
#!/usr/bin/env bash
exec /opt/myimages/venv/bin/myimages "$@"
LAUNCH
chmod +x "${STAGE}/${PKG}/usr/bin/myimages"
install -m 0644 "${ROOT}/packaging/myimages.desktop" \
    "${STAGE}/${PKG}/usr/share/applications/myimages.desktop"
"${INSTALL_DIR}/venv/bin/python" "${ROOT}/scripts/export_icon.py" \
    "${STAGE}/${PKG}/usr/share/icons/hicolor/256x256/apps/myimages.png" 256

echo "==> Control metadata"
mkdir -p "${STAGE}/${PKG}/DEBIAN"
cat > "${STAGE}/${PKG}/DEBIAN/control" <<CONTROL
Package: myimages
Version: ${VERSION}
Section: graphics
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10)
Recommends: ffmpeg
Maintainer: Aleksandr <wachawo@gmail.com>
Description: Lightweight photo and video viewer, editor and converter
 View photos and videos with thumbnails, crop and convert images, combine
 images into a size-controlled PDF, find duplicates, batch rename and export
 GIFs. Extensible through plugins.
CONTROL

echo "==> Building package"
dpkg-deb --build --root-owner-group "${STAGE}/${PKG}" "${ROOT}/${PKG}.deb"
echo "Built ${ROOT}/${PKG}.deb"
rm -rf "${STAGE}"
