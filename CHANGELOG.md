# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- myImages adds itself to the application menu the first time it runs, on
  Linux, so its icon is there without anyone opening a settings dialog to ask
  for it. It happens once: an entry you delete stays deleted, and a packaged
  build's own entry is left alone.
- Screenshots of the interface in the README, and `scripts/make_demo_shots.py`
  that regenerates them from the real application so they cannot drift away
  from what it looks like.

### Fixed

- The duplicate finder reported an identical pair twice — once as identical
  bytes and again as visually similar — pre-checked its extra copy in both, and
  handed the same path to the deleter twice.

### Changed

- The zoom and fit controls no longer take a strip of their own under the
  picture: they float over it, bottom left, at the same height as the
  resolution badge opposite. The resolution stays in the corner where it was.
- The editor's panes sit on a line of their own above the tools, so the tabs no
  longer compete for width with the things they switch between — every pane's
  row now fits, and the editor's minimum width drops from 509 to 360.
- The editor is now three panes — **Edit**, **Crop** and **Background** — chosen
  with tabs. One row carrying every tool wanted more width than the window
  gives it, so Save as Copy and Cancel sat past the right-hand edge at the
  application's own default size. Save, Save as Copy and Cancel are now pinned
  where no window width can hide them, and each pane's row fits with room to
  spare.
- Edit holds rotating, mirroring and a new **Resize**: set the picture's size in
  pixels, with the shape locked or free. It says when a resize would enlarge,
  because that invents pixels rather than finding detail.
- Crop's shapes are buttons that light when they are on, ordered widest to
  tallest so the row is one progression through the square: 16:9 to 9:16, with
  1:1 in the middle. **N:N** at the end holds no shape at all, and pressing a
  lit button releases the lock as well. A field beside them, sized to match a
  button, takes a shape no button holds — a print cover is 0.7667, which is
  nobody's camera preset.
- Background holds removing the background and removing a watermark, with the
  three cut-out settings behind one button rather than spread across the row.
- Zooming is now **Ctrl**+wheel rather than Shift+wheel, matching every other
  application that zooms with a wheel.
- Every icon's tooltip is a few words rather than a sentence. A tooltip is read
  at a glance, and one long enough to be a sentence is read as a paragraph and
  skipped. A test walks the real windows and fails on an icon with no tooltip
  or one over five words, so neither can creep back in.
- The folder icon is a folder: a single outline whose tab breaks the top edge.
  It was a rectangle with two short lines beside it, which read as a box.


### Fixed

- Switching away from the cut-out tools silently discarded the cut-out. The
  edits stayed in the list while the editor ignored them, so Save rewrote the
  original with the untouched picture — the work vanished and a JPEG was
  re-encoded for nothing. What Save writes now follows the edits rather than
  which set of controls happens to be on screen.
- The application icon now appears in the taskbar. The icon was always being
  published; what was missing was the window's identity — it told GTK shells,
  KDE and Wayland that it was "python3", so a panel matched it to the
  interpreter and drew the interpreter's icon. The desktop entry also names the
  window class a panel matches a running window on.
- Saving an image threw away its print resolution. Every format lost it, and
  TIFF and BMP wrote a *wrong* one — a 300 dpi scan opened, rotated and saved
  came back claiming 1 dpi or 96 dpi. The value is now carried across, and
  formats that cannot record one (WebP, GIF) are left alone rather than asked.
- Thumbnails no longer inherit the resolution of the photograph they came from,
  which described a pixel count they do not have.


## [0.0.2] - 2026-08-04

### Added

- `myimages --version`.
- A macOS build: `myImages-<ver>-macos-<arch>.dmg`, one for Apple Silicon and
  one for Intel. It is ad-hoc signed but not notarised, so the README explains
  the one command that clears the quarantine flag.
- A Windows build: unpack `myImages-<ver>-windows-x64.zip` and run
  `myimages.exe`. It carries its own Python, so nothing needs installing first.
  It is unsigned, and the README says how to get past SmartScreen.

- Automatic background removal in the editor: one press finds the subject with
  a model and clears the rest. It needs the optional extra
  (`pip install "myimages[bgremove]"`) and a one-off model download, and the
  editor offers both rather than leaving the button inert. The result joins the
  edit list like any other step, so Undo removes it and the wand, eraser and
  restore brush still refine it.
- Background removal in the image editor. A **Cut out** mode with a magic wand
  (click a colour to clear its region), an eraser, a restore brush that paints
  the original back, and a Soften control for the edge. Reachable from the
  toolbar and from **Remove Background** on the right-click menu. Edits are
  recorded as geometry rather than pixels, so Undo steps back one wand click or
  one brush stroke at a time and the result is re-rendered at full resolution
  when you save.
- Hold **Compare** in the editor to see the picture before the cut, and cycle
  the backdrop between a checkerboard, white, black and magenta to spot a
  leftover fringe.
- The engine behind automatic background removal: the ISNet segmentation model,
  run through ONNX Runtime directly. The weights are fetched once, verified
  against their checksum, into `~/.myimages/models/`. It is an optional extra —
  `pip install "myimages[bgremove]"` — and nothing calls it yet.
- A checkerboard behind transparent pixels in the editor canvas, so a cut-out no
  longer looks like a very dark subject, and a brush outline that follows the
  cursor at the size the edit will actually have.

- The mask engine behind background removal: a magic wand that clears a
  connected patch of similar colour, an eraser, a restore brush that paints the
  original back, and an edge-softening pass. Edits are recorded as geometry
  rather than pixels, so undo steps back one wand pick or one brush stroke and
  the saved file is re-rendered at full resolution from the same list the
  preview used. Nothing calls it yet.

### Changed

- The name in the top bar is now a wordmark: **MY** in a light blue against
  **IMAGES** in the interface's own text colour, set larger and heavier. Both
  colours come from the active theme, so it stays legible on the light one.
- Removing a watermark no longer freezes the window. It runs off the interface
  thread behind a progress dialog, and the tools that share the working image —
  Crop, Remove Watermark, Save and Save as Copy — are disabled until it
  finishes, so a second press cannot race the first.
- Save writes a sibling `.png` and leaves the original untouched when the source
  format cannot store transparency (JPEG, BMP and GIF). Formats that support
  alpha — PNG, WebP and TIFF — are still overwritten in place. Nothing is
  flattened without being asked for, and no original is deleted.

### Fixed

- The Debian package and the AppImage now work. Both carried a virtualenv whose
  launcher pointed at a build directory that no longer existed, and neither
  contained a Python interpreter at all, so the installed command died with
  "bad interpreter". Both are now built from one frozen bundle that carries its
  own runtime.
- Bundled plugins are found in packaged builds. The loader scanned for `.py`
  files on disk, which a packaged build does not have, so the 3D preview
  silently disappeared from every artifact while working from a source
  checkout.
- Desktop-integration settings are shown only on Linux. Elsewhere they wrote a
  `.desktop` file that could never take effect and then reported success.
- Optional features cannot be pip-installed into a packaged build, and now say
  so instead of relaunching the application. Those builds ship what they
  support already.
- Install advice for FFmpeg names the command for the platform you are on
  rather than always suggesting `apt`.
- The helper processes the app runs no longer flash a console window on
  Windows — one per video thumbnail as a gallery scrolled.

- Saving an image with transparency over a JPEG destroyed the original. Pillow
  opens the destination for writing before the encoder rejects the mode, so the
  photograph was truncated to zero bytes and then an error was raised that never
  reached the interface. Whether a format can hold transparency is now checked
  before the file is opened.
- Opening a file the decoder cannot read, and every failure while saving, are
  now reported. Both used to raise inside a Qt slot, where the exception was
  discarded and the button simply appeared to do nothing.

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

[Unreleased]: https://github.com/wachawo/myImages/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/wachawo/myImages/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/wachawo/myImages/releases/tag/v0.0.1
