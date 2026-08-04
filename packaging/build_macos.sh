#!/usr/bin/env bash
# Build the macOS artifact: a .app bundle inside a .dmg.
#
# One architecture per run, matching the machine it runs on. There is no
# universal2 wheel for PySide6, so an arm64 build and an Intel build are two
# separate builds from two separate runners rather than one fat binary.
#
# Usage: bash packaging/build_macos.sh [version]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${ROOT}/myimages/__init__.py")"
VERSION="${1:-${DEFAULT_VERSION}}"
ARCH="$(uname -m)"
STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}" "${ROOT}/packaging/myimages.icns"' EXIT

PYTHON="${PYTHON:-python3}"

echo "==> Rendering the icon set"
# iconutil wants a .iconset directory of named sizes; the app paints its own
# icon at any size, so each one is rendered rather than resampled.
ICONSET="${STAGE}/myimages.iconset"
mkdir -p "${ICONSET}"
for size in 16 32 128 256 512; do
    "${PYTHON}" "${ROOT}/scripts/export_icon.py" "${ICONSET}/icon_${size}x${size}.png" "${size}"
    "${PYTHON}" "${ROOT}/scripts/export_icon.py" \
        "${ICONSET}/icon_${size}x${size}@2x.png" "$((size * 2))"
done
iconutil --convert icns --output "${ROOT}/packaging/myimages.icns" "${ICONSET}"

echo "==> Freezing the application"
"${PYTHON}" -m PyInstaller --clean --noconfirm \
    --distpath "${STAGE}/dist" --workpath "${STAGE}/build" \
    "${ROOT}/packaging/myimages.spec"

APP="${STAGE}/dist/myImages.app"
[ -d "${APP}" ] || { echo "The build produced no .app bundle" >&2; exit 1; }

echo "==> Smoke test"
# The binary inside the bundle, run directly: a .app cannot be launched with
# arguments through `open` and still have its output captured.
REPORTED="$("${APP}/Contents/MacOS/myimages" --version)"
echo "    ${REPORTED}"
case "${REPORTED}" in
    *"${VERSION}"*) ;;
    *) echo "The bundle reports '${REPORTED}', expected ${VERSION}" >&2; exit 1 ;;
esac

echo "==> Checking the signature"
# PyInstaller ad-hoc signs when given no identity. On Apple Silicon that is not
# optional: an unsigned Mach-O will not execute at all.
codesign --verify --deep --strict "${APP}" && echo "    signature verifies"

echo "==> Packing the disk image"
DMG_ROOT="${STAGE}/dmg"
mkdir -p "${DMG_ROOT}"
cp -R "${APP}" "${DMG_ROOT}/"
# The Applications symlink is the whole install instruction: open the image,
# drag the icon across.
ln -s /Applications "${DMG_ROOT}/Applications"
IMAGE="${ROOT}/myImages-${VERSION}-macos-${ARCH}.dmg"
rm -f "${IMAGE}"
hdiutil create -volname "myImages ${VERSION}" -srcfolder "${DMG_ROOT}" \
    -ov -format UDZO "${IMAGE}" >/dev/null
echo "Built ${IMAGE}"
