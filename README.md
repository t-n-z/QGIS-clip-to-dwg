# Clip to DWG

A small QGIS plugin that adds a single toolbar button. Press it, draw a box on
the map, and all currently visible vector layers are clipped to that box and
exported as a single DWG file ready for AutoCAD, Civil 3D, BricsCAD, and other
CAD tools.

![Plugin icon](icon.svg)

## What it does

- Adds a **Clip to DWG** toolbar button and Vector menu entry.
- Two selection modes:
  - **Two-click**: click one corner, move, click the opposite corner.
  - **Click-drag**: press, drag a box of at least 50 pixels, release.
- Shows a **pre-flight list** of exactly what is about to be exported: each
  layer, its geometry type, how many features fall inside the box, and what it
  will produce - with tick boxes to narrow the selection.
- Clips the chosen layers at the box boundary (true geometric intersection,
  not attribute filtering).
- Exports the result as a single DWG file at a location you choose.
- Writes layers **bottom of the Layers panel first**, so the top of the panel
  ends up on top in CAD.
- Polygon fill patterns are written as DWG `HATCH` entities, with their
  opacity preserved.
- All other entities (lines, polylines, points, text) are written with
  **ByLayer** color, linetype, and lineweight so you can control appearance
  in the CAD layer manager.
- Fully transparent hatches are dropped automatically.

## Requirements

- **QGIS 3.4 LTR or later** on Windows, Linux, or macOS.
- **ODA File Converter** from the Open Design Alliance. Free download from
  <https://www.opendesign.com/guestfiles/oda_file_converter>. Install it
  once; the plugin will prompt for its executable path on first run and
  remember it for future use. QGIS and GDAL cannot write DWG natively, so
  this external tool is used to convert the intermediate DXF into a DWG.

## Installation

### From the QGIS plugin repository (recommended)

1. In QGIS, open **Plugins → Manage and Install Plugins**.
2. Search for **Clip to DWG**.
3. Click **Install Plugin**.

### From a ZIP

1. Download `clip_to_dwg.zip` from the
   [Releases page](https://github.com/t-n-z/QGIS-clip-to-dwg/releases).
2. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Browse to the ZIP, click **Install Plugin**.

### Manual install (for development)

Drop the plugin folder into your QGIS profile's plugins directory:

- **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

Then enable the plugin via the Plugin Manager.

## Usage

1. Make sure the vector layers you want to export are **visible** (ticked) in
   the Layers panel. Hidden layers and raster layers are ignored.
2. Click the **Clip to DWG** toolbar button.
3. On first run only, a dialog explains the ODA File Converter requirement
   and asks you to point at its executable.
4. Choose one of two selection modes on the map canvas:
   - **Two-click**: click one corner, move the mouse, click the opposite
     corner.
   - **Click-drag**: press, drag at least 50 pixels, release.
5. A Save dialog asks for the output DWG location. The dialog title
   indicates whether your project CRS is in metres or feet so you know
   what numeric values the DWG will contain.
6. The plugin clips the layers, writes a temporary DXF, then runs the ODA
   File Converter in a background task to produce the DWG. A message bar
   notification confirms success or surfaces any error.

Press **Escape** or **right-click** at any time during box drawing to
cancel.

## Coordinate Reference System

Output coordinates are in the **current QGIS project CRS**. No reprojection
is performed. DWG files have no CRS metadata, so remember which CRS the
project was using when you exported.

## Layer scope

- Layers are taken from the **tick boxes** in the Layers panel. Selecting or
  highlighting a layer does not affect the export.
- Layers inside a group set to **"Render Layers as a Group"** are included.
  (They were not before 1.1.0 - see the changelog.)
- Scale-dependent visibility is ignored: a ticked layer that is hidden at the
  current zoom is still exported. The box you drew has nothing to do with the
  zoom you happened to be at.
- Raster layers are ignored (DWG is vector only).
- A layer with no features inside the box, or no CRS, is listed as such in the
  pre-flight and named in the message bar rather than quietly skipped.
- Layer names in the DWG match the QGIS layer names.

## Known limitations

- No numeric box entry.
- DWG version is fixed at ACAD2018.
- SVG fills, raster fills, and gradient fills do not translate to DWG
  hatches.
- The plugin assumes the ODA File Converter CLI signature has not changed
  (stable for many years, but not guaranteed).
- Not yet tested on macOS where the ODA executable lives inside an `.app`
  bundle.

## Settings

The ODA File Converter executable path is stored in QGIS settings under
`ClipToDwg/oda_converter_path`. To change it, edit the value in
**Settings → Options → Advanced**, or simply delete the entry to be prompted
again on next run.

## License

Released under the **GNU General Public License v2.0**. See
[LICENSE](LICENSE) for the full text.

The toolbar icon is from [SVG Repo](https://www.svgrepo.com/svg/60485/dwg)
under Creative Commons Zero (CC0).

## Author

Tom M (CDSS) — <qgis@cdss.co.nz>

## Issues and contributions

Bug reports and feature requests:
<https://github.com/t-n-z/QGIS-clip-to-dwg/issues>.

Pull requests welcome.

## Changelog

### 1.2.0

**Now runs on QGIS 4 / Qt6.**

Every Qt and QGIS enum is written in the scoped form
(`Qt.MouseButton.LeftButton`, `Qgis.MessageLevel.Info`, …) and `exec_()` is now
`exec()`. On Qt6 the unscoped spellings are *all* `AttributeError` and
`QDialog.exec_` does not exist, so the plugin could not run there at all. The
scoped spellings resolve to identical values on Qt5, so one codebase serves
both — verified on **QGIS 3.44.10 (Qt 5.15.13)** and **QGIS 4.0.2 (Qt 6.11.0)**:
same plugin load, same dialog, same 552 `HATCH` entities from the same data.

Two genuine Qt6 bugs found on the way, both of which would have shipped:

- **A successful export was reported as a failure.** `QgsDxfExport.writeToFile`
  returns an `ExportResult` enum. The old check was `!= 0`, which is `True` on
  PyQt6 because the enum is no longer an `int` subclass — so a clean export
  raised *"returned error ExportResult.Success"*. Now compared against
  `ExportResult.Success`.
- **The no-fill test would never have fired.** It used `int()` on a Qt enum,
  which raises `TypeError` on PyQt6.

**Tidied for the repository's code scanners**

- The three near-identical symbol-layer walks are now one shared helper
  (`preflight.symbol_layers`), which is where most of the duplication and most
  of the swallowed exceptions lived.
- Every tolerated failure is written to the Log Messages panel rather than
  passed over in silence, and the handlers name the three failure modes they
  actually expect (`AttributeError`, `TypeError`, `RuntimeError`) instead of
  catching everything.
- Ambiguous single-letter variable names removed; all lines within 79 columns.
- The ODA subprocess call carries a reviewed justification: list form,
  `shell=False`, path chosen by the user through a file dialog and
  existence-checked before launch, so nothing is shell-interpreted.

### 1.1.0

**Fixed: whole groups of layers could be left out of the export, silently.**

The plugin took its layer list from `checkedLayers()`. Once a group is set to
**"Render Layers as a Group"** (QGIS 3.24+), that call returns the group
*composite* - a `QgsGroupLayer`, which is not a vector layer - instead of the
layers inside it. A vector-layer filter therefore discarded the group and
everything in it, with no warning, and the DWG came out holding only whatever
else happened to be ticked.

Measured on a `TOP / GRP(A, B)` tree: `checkedLayers()` returns `['TOP']`
where the layer tree holds `['TOP', 'A', 'B']`. Enumeration now walks the
layer tree directly and resolves visibility up the parent chain.

**Added**

- A **pre-flight list** before every export: each layer going in, its geometry,
  its feature count inside the box, and what it will produce (hatches +
  outlines / lines / points), with tick boxes to narrow the set.
- **Draw order.** Layers are written bottom-of-panel first, so the top of the
  Layers panel lands on top in CAD. A layer's own hatch is still written before
  its outlines. A custom layer order, where set, takes precedence.

**Resiliency**

- Per-layer accounting in the Log Messages panel every run: features in,
  features exported, whether hatches were produced, and any error.
- Layers that produced nothing are named in the message bar instead of going
  missing from the output without comment.
- A layer with **no CRS** is listed as unusable and skipped by name, rather
  than QGIS raising an unexplained projection dialog part-way through.
- A polygon layer with **no fill** is called out ("outlines only - no
  hatches"). Correct behaviour, but it should not be a surprise in CAD.
- Fixed: the internal clip box was built from the project CRS `authid()`, which
  is empty for a **custom CRS**, leaving that layer CRS-less and triggering a
  projection prompt with nothing to say what had asked for it.
- Errors in the clip and boundary-line passes are recorded against the layer
  instead of being swallowed.

### 1.0.1

- Polylines exported at width 0.
- Symbol layers that are eye-toggled off, fully transparent, or set to NoBrush
  are honoured, suppressing `HATCH` output for features hidden in QGIS.
- Polygon boundaries are cut at the selection box instead of closing along it.

### 1.0.0

- First public release.
- Two selection modes: two-click corners or click-drag box.
- Visible vector layers clipped to bbox and exported to DWG via ODA File
  Converter.
- HATCH entities exported for QGIS fill patterns, with opacity preserved.
- Fully transparent hatches dropped automatically.
- All non-hatch entities forced to ByLayer color, linetype, and lineweight.
- First-run dialog explains ODA File Converter and links to download.
