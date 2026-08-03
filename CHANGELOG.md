# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.1] - 2026-08-03

First public release.

### Added

- Folder browsing with optional recursion, live refresh when files change on
  disk, and an on-disk thumbnail cache.
- Photo preview with fit, wheel zoom and pan; video preview through Qt
  Multimedia with a graceful fallback when the backend is unavailable.
- File list panel with three views (thumbnail grid, names, sortable table),
  name search, favourites and multi-select.
- Inline image editor: rotate, mirror, aspect-locked crop, save or save as
  copy, format conversion (JPEG/PNG/WebP/BMP/TIFF/GIF) and greyscale.
- Watermark removal for corner badges, or for any region drawn by hand.
- Images to PDF with page quality, maximum edge, greyscale and an optional
  target file size the builder meets by lowering quality.
- Video tools through ffmpeg: trim, crop, scale and GIF export.
- GIF assembly from selected images.
- Duplicate finder using exact content hashes and adjustable perceptual
  hashing, with bulk deletion of the extras.
- Batch rename with a filename mask and live preview.
- Deletion to the system trash when Send2Trash is installed.
- Plugin system for previewing additional file types, with a bundled 3D model
  example.
- Dark and light themes, remembered layout, and desktop integration that
  installs into the user's own `~/.local/share` without root.
- Packaging scripts for a `.deb` and an AppImage.

[Unreleased]: https://github.com/wachawo/myImages/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/wachawo/myImages/releases/tag/v0.0.1
