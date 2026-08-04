# myImages

A lightweight desktop viewer, editor and converter for photos **and** videos,
built with PySide6. It looks like a compact, dark, icon-driven gallery (a close
cousin of the sibling *myPhotos* project) but adds a tool panel,
inline image editing, PDF/GIF export and preview, duplicate finding, batch
rename and a plugin system.

The runtime core is deliberately tiny — **PySide6 + Pillow**. Everything else
(ffmpeg for video, trash support, HEIC) is optional and can be installed from
inside the app.

## Features

- **Browse** a folder, optionally including its sub-folders. The list keeps
  itself up to date when files are added, deleted or edited by other
  programs, and only the thumbnails that actually changed are rebuilt.
- **Preview** photos with fit / wheel-zoom / pan, and videos with Qt Multimedia
  (falls back to a note + the video tools when the backend is absent).
- **Navigate** with **←/→** or the mouse wheel; **Shift**+wheel zooms and never
  zooms out past the fit-to-window size.
- **File list** on a panel that can sit on either side: three views (thumbnail
  grid, plain names, or a sortable table with clickable headers), a name-search
  box, **favourites** (**F**, shown as a star), and multi-select. Its width is
  set in whole thumbnail columns — one to four — so the grid always fills the
  panel instead of leaving a ragged strip of empty space.
- **Edit images inline** under the preview (double-click a thumbnail, or the
  pencil icon): rotate, mirror horizontally or vertically, pick an aspect ratio
  that locks the crop box, **Crop**, then **Save** (overwrite) or
  **Save as Copy**; plus format conversion
  (JPEG/PNG/WebP/BMP/TIFF/GIF) and colour → black & white.
- **Remove a watermark**: the badge generators stamp into a corner is detected
  and painted over with its surroundings. Draw a selection first to clean a
  mark anywhere else. The result opens in the editor, so nothing is written
  until you approve it.
- **Remove the background**: switch the editor to **Cut out** (or use the wand
  on the toolbar). Click a colour with the magic wand to clear its region, drag
  the eraser to take more away and the restore brush to paint the picture back,
  and soften the edge. Hold **Compare** to see the original, and cycle the
  backdrop between a checkerboard, white, black and magenta to spot a leftover
  fringe. Every step is undoable one at a time. Saving over a JPEG writes a
  PNG beside it, since a JPEG cannot hold transparency; the button says so
  before you press it.
- **Right-click** a photo or a thumbnail for Copy File, Copy Filename, Copy
  Picture, Delete, Rename, Select, Edit Image, Rotate, Convert, Remove
  Watermark and Remove Background. **Rename** here renames that one file; the toolbar keeps the
  pattern-based batch rename for a whole selection.
- **Images → PDF**: combine a selection into one PDF with control over page
  quality, maximum edge and greyscale, plus an optional **target file size** the
  builder meets by lowering quality automatically.
- **Video tools** (via ffmpeg): trim on a timeline, crop the sides, scale, and
  export a GIF of the trimmed range.
- **GIF from frames**: build an animated GIF from several selected images.
- **Find duplicates**: exact (content hash) and visually similar (perceptual
  hash, adjustable) with one-click bulk delete of the extras.
- **Batch rename** with a filename mask and a live preview (one file at a time
  is the plain box on the right-click menu).
- **Delete** to the system trash when Send2Trash is installed.
- **Plugins**: drop a `*.py` viewer into the plugins folder to preview new file
  types (a 3D-model example ships in `myimages/plugins/`).
- **Themes** (dark/light), remembered layout, on-disk thumbnail cache.
- **Desktop integration** (Settings → Desktop): add myImages to the application
  menu and make it the default for the photo and video types it opens. Both
  install into your own `~/.local/share`, need no root, and can be undone from
  the same place. Opening a photo from a file manager loads its whole folder,
  so you can step through the gallery from there.

## Run from source

Requires Python 3.10+ and (for video features) ffmpeg on the `PATH`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python main.py          # or: myimages
```

`main.py` in the repository root is just a thin shell around
`myimages.app.main`; all the real code lives in the `myimages` package.

Pressing `Ctrl+C` in the launching terminal closes the app the normal way, so
the window layout and settings are still saved on the way out.

## Optional features

Open **Optional features** (the puzzle icon) in the app to see what is missing
and install the Python ones (Send2Trash, pillow-heif) with a click. ffmpeg is a
system tool — install it with your package manager:

```bash
sudo apt install ffmpeg
```

## Develop

```bash
pip install -e ".[dev,trash,heif]"
pre-commit install
make check          # ruff + mypy + pytest (>90% coverage gate)
```

Individual gates: `make lint`, `make typecheck`, `make test`, `make format`.

The code style is strict on purpose: `ruff`, `black`, `mypy --strict`,
self-documenting names (no leading-underscore identifiers) and a docstring on
every public function. The pure logic (imaging, video, scanning, dedup, rename)
is fully unit-tested; the PySide6 UI is tested offscreen with `pytest-qt`.

## Build a package

```bash
make deb        # -> myimages_<ver>_<arch>.deb   (bundled venv under /opt/myimages)
make appimage   # -> myImages-<ver>-x86_64.AppImage
```

Both stage a self-contained virtualenv, add a launcher, the `.desktop` file and
a rendered icon. See `packaging/` for the scripts.

## Project layout

| Path                       | Purpose                                             |
|----------------------------|-----------------------------------------------------|
| `main.py`                  | Shell entry point (`python main.py`)                |
| `myimages/app.py`          | QApplication bootstrap: logging, theme, plugins     |
| `myimages/config.py`       | JSON-backed settings model                          |
| `myimages/theme.py`, `icons.py` | Dark/light theme and painted vector icons      |
| `myimages/core/`           | Media model, scanning, thumbnails, dedup, rename, deletion, folder watching, plugins, dependencies |
| `myimages/imaging/`        | Convert, transform (crop/scale/rotate/grey), PDF    |
| `myimages/video/`          | ffmpeg wrapper, trim, crop/scale, GIF               |
| `myimages/gui/`            | PySide6 window, panels, viewers and tool dialogs    |
| `myimages/plugins/`        | Bundled example plugins (3D model info)             |
| `tests/`                   | Pytest suite (offscreen, synthetic assets)          |
| `packaging/`               | `.deb` / AppImage build scripts and `.desktop`      |

See [the roadmap](https://github.com/wachawo/myImages/blob/main/docs/roadmap.md)
for the plugin API and planned work.

## Storage

Everything the app persists lives under `~/.myimages/`:

- `settings.json` — all preferences and favourites,
- `thumbnails/` — the on-disk thumbnail cache,
- `plugins/` — drop your own `*.py` viewer plugins here.

Point `MYIMAGES_DATA_DIR` elsewhere to relocate all of it (the test suite uses
this to stay isolated).

## Watching the folder

While a folder is open the app follows changes made to it elsewhere. A check
reads the directory listing only — never the pictures — so it stays cheap:
a folder of 3 000 photos (428 MB) costs about **114 ms** per check, on a
worker thread, every 10 s by default. The operating system also reports
changes instantly, so the timer is only a safety net for network shares.

Optionally (**Settings → Also verify file checksums**) a handful of files per
check are also md5-summed. That catches a file rewritten *without* changing
its size or date, which no amount of `stat`-ing can see. Only a small
rotating batch is hashed per pass, so the whole folder is still covered over
time without ever re-reading every photo at once — hashing 3 000 photos in
one pass would cost roughly 0.9 s and 428 MB of reads.
