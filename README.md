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
- Clips every visible vector layer at the box boundary (true geometric
  intersection, not attribute filtering).
- Exports the result as a single DWG file at a location you choose.
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
3. On first run only or if dependency not found, a dialog explains the ODA File Converter requirement
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

- "Visible" means vector layers ticked in the Layers panel.
- Raster layers are silently ignored (DWG is vector only).
- A visible layer with no features inside the box is silently skipped.
- Layer names in the DWG match the QGIS layer names.

## Known limitations

- No way to pick a subset of visible layers (export is all-or-nothing for
  visible vectors).
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

### 1.0.0

- First public release.
- Two selection modes: two-click corners or click-drag box.
- Visible vector layers clipped to bbox and exported to DWG via ODA File
  Converter.
- HATCH entities exported for QGIS fill patterns, with opacity preserved.
- Fully transparent hatches dropped automatically.
- All non-hatch entities forced to ByLayer color, linetype, and lineweight.
- First-run dialog explains ODA File Converter and links to download.
