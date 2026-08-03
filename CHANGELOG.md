# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A checkerboard behind transparent pixels in the editor canvas, so a cut-out no
  longer looks like a very dark subject, and a brush outline that follows the
  cursor at the size the edit will actually have. Nothing switches the canvas
  into those modes yet.

- The mask engine behind background removal: a magic wand that clears a
  connected patch of similar colour, an eraser, a restore brush that paints the
  original back, and an edge-softening pass. Edits are recorded as geometry
  rather than pixels, so undo steps back one wand pick or one brush stroke and
  the saved file is re-rendered at full resolution from the same list the
  preview used. Nothing calls it yet.

### Fixed

- Saving an image with transparency over a JPEG destroyed the original. Pillow
  opens the destination for writing before the encoder rejects the mode, so the
  photograph was truncated to zero bytes and then an error was raised that never
  reached the interface. Whether a format can hold transparency is now checked
  before the file is opened.
- Opening a file the decoder cannot read, and every failure while saving, are
  now reported. Both used to raise inside a Qt slot, where the exception was
  discarded and the button simply appeared to do nothing.

### Changed

- Removing a watermark no longer freezes the window. It runs off the interface
  thread behind a progress dialog, and the tools that share the working image —
  Crop, Remove Watermark, Save and Save as Copy — are disabled until it
  finishes, so a second press cannot race the first.
- Save writes a sibling `.png` and leaves the original untouched when the source
  format cannot store transparency (JPEG, BMP and GIF). Formats that support
  alpha — PNG, WebP and TIFF — are still overwritten in place. Nothing is
  flattened without being asked for, and no original is deleted.

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
