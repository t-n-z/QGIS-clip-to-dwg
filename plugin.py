"""
Clip to DWG plugin for QGIS 3.4+

Workflow:
1. User clicks the toolbar action.
2. User clicks two opposite corners on the map canvas. A rubber band shows
   the box live while the cursor moves.
3. A Save dialog asks for the output DWG name.
4. Visible vector layers are clipped to the box (geometric intersection).
5. Clipped layers are written to a temp DXF using QgsDxfExport.
6. ODA File Converter is invoked in a background task to produce the DWG.
7. The DWG is moved to the user's chosen path.
"""

import os
import tempfile
import shutil
import subprocess

from qgis.PyQt.QtCore import Qt, QSettings, QFile, QIODevice
from qgis.PyQt.QtGui import QIcon, QColor, QCursor
from qgis.PyQt.QtWidgets import QAction, QFileDialog, QMessageBox

from qgis.core import (
    QgsProject,
    QgsRectangle,
    QgsPointXY,
    QgsGeometry,
    QgsFeature,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsMapLayer,
    QgsUnitTypes,
    QgsDxfExport,
    QgsTask,
    QgsApplication,
    QgsMessageLog,
    QgsRenderContext,
    Qgis,
)
from qgis.gui import QgsMapTool, QgsRubberBand

import processing


PLUGIN_NAME = "Clip to DWG"
SETTINGS_ODA_PATH = "ClipToDwg/oda_converter_path"


# ----------------------------------------------------------------------------
# Map tool: two-click bounding box with live rubber band
# ----------------------------------------------------------------------------
class BoxMapTool(QgsMapTool):
    DRAG_THRESHOLD_PX = 50

    def __init__(self, canvas, on_complete, on_cancel):
        super().__init__(canvas)
        self.canvas = canvas
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.first_point = None
        self.press_screen_pos = None

        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setColor(QColor(255, 0, 0, 200))
        self.rubber_band.setFillColor(QColor(255, 0, 0, 40))
        self.rubber_band.setWidth(2)

        self.setCursor(QCursor(Qt.CrossCursor))

    def canvasPressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._cancel()
            return
        if event.button() != Qt.LeftButton:
            return

        point = self.toMapCoordinates(event.pos())
        if self.first_point is None:
            self.first_point = point
            self.press_screen_pos = event.pos()
        else:
            rect = QgsRectangle(self.first_point, point)
            self._cleanup()
            self.on_complete(rect)

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.first_point is None or self.press_screen_pos is None:
            return
        delta = event.pos() - self.press_screen_pos
        dist = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
        if dist < self.DRAG_THRESHOLD_PX:
            # Treat as first click of two-click mode. Keep first_point.
            return
        point = self.toMapCoordinates(event.pos())
        rect = QgsRectangle(self.first_point, point)
        self._cleanup()
        self.on_complete(rect)

    def canvasMoveEvent(self, event):
        if self.first_point is None:
            return
        current = self.toMapCoordinates(event.pos())
        self._draw_rect(self.first_point, current)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._cancel()

    def _draw_rect(self, p1, p2):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        corners = [
            QgsPointXY(p1.x(), p1.y()),
            QgsPointXY(p2.x(), p1.y()),
            QgsPointXY(p2.x(), p2.y()),
            QgsPointXY(p1.x(), p2.y()),
        ]
        for pt in corners:
            self.rubber_band.addPoint(pt, False)
        # close polygon with do_update=True to repaint
        self.rubber_band.addPoint(corners[0], True)

    def _cleanup(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        self.canvas.unsetMapTool(self)

    def _cancel(self):
        self._cleanup()
        self.on_cancel()

    def deactivate(self):
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)
        super().deactivate()


# ----------------------------------------------------------------------------
# Background task: run ODA File Converter and move the resulting DWG
# ----------------------------------------------------------------------------
class DwgConvertTask(QgsTask):
    def __init__(self, dxf_dir, output_dwg_path, oda_path):
        super().__init__("Converting DXF to DWG", QgsTask.CanCancel)
        self.dxf_dir = dxf_dir
        self.output_dwg_path = output_dwg_path
        self.oda_path = oda_path
        self.error = None

    def run(self):
        out_tmpdir = None
        try:
            out_tmpdir = tempfile.mkdtemp(prefix="cliptodwg_out_")
            # ODA File Converter CLI signature:
            #   ODAFileConverter <in_dir> <out_dir> <out_ver> <out_fmt> <recurse> <audit> <filter>
            cmd = [
                self.oda_path,
                self.dxf_dir,
                out_tmpdir,
                "ACAD2018",
                "DWG",
                "0",   # do not recurse
                "1",   # audit
                "*.DXF",
            ]
            proc = subprocess.run(
                cmd, capture_output=True, timeout=300
            )
            if proc.returncode != 0:
                self.error = (
                    "ODA File Converter exited with code "
                    f"{proc.returncode}: "
                    + proc.stderr.decode(errors="ignore")[:500]
                )
                return False

            produced = os.path.join(out_tmpdir, "out.dwg")
            if not os.path.exists(produced):
                self.error = "ODA File Converter did not produce a DWG."
                return False

            # Replace existing target if any
            if os.path.exists(self.output_dwg_path):
                os.remove(self.output_dwg_path)
            shutil.move(produced, self.output_dwg_path)
            return True
        except subprocess.TimeoutExpired:
            self.error = "ODA File Converter timed out."
            return False
        except Exception as e:
            self.error = str(e)
            return False
        finally:
            shutil.rmtree(self.dxf_dir, ignore_errors=True)
            if out_tmpdir:
                shutil.rmtree(out_tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# Plugin
# ----------------------------------------------------------------------------
class ClipToDwgPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.map_tool = None
        self.previous_tool = None
        self._oda_path = None

    # --- QGIS plugin lifecycle ---------------------------------------------
    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        self.action = QAction(
            QIcon(icon_path), PLUGIN_NAME, self.iface.mainWindow()
        )
        self.action.setToolTip(
            "Clip visible vector layers to a box and export to DWG"
        )
        self.action.triggered.connect(self.start)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu(PLUGIN_NAME, self.action)

    def unload(self):
        self.iface.removePluginVectorMenu(PLUGIN_NAME, self.action)
        self.iface.removeToolBarIcon(self.action)

    # --- Helpers ------------------------------------------------------------
    def _flash(self, text, level=Qgis.Info, duration=4):
        self.iface.messageBar().pushMessage(
            PLUGIN_NAME, text, level=level, duration=duration
        )

    def _get_visible_vector_layers(self):
        root = QgsProject.instance().layerTreeRoot()
        return [
            l for l in root.checkedLayers()
            if l.type() == QgsMapLayer.VectorLayer
        ]

    def _ensure_oda_path(self):
        s = QSettings()
        path = s.value(SETTINGS_ODA_PATH, "", type=str)
        if path and os.path.exists(path):
            return path

        box = QMessageBox(self.iface.mainWindow())
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("ODA File Converter required")
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setText(
            "<p><b>Clip to DWG</b> needs the free "
            "<b>ODA File Converter</b> to produce DWG files. "
            "QGIS and GDAL cannot write DWG natively, so this external "
            "tool is used to convert the intermediate DXF to DWG.</p>"
            "<p>Download it from the Open Design Alliance:<br>"
            "<a href=\"https://www.opendesign.com/guestfiles/oda_file_converter\">"
            "https://www.opendesign.com/guestfiles/oda_file_converter</a></p>"
            "<p>Install it, then click <b>Select...</b> and point at the "
            "<code>ODAFileConverter</code> executable. The location is "
            "remembered for future runs.</p>"
            "<p>Click <b>Go Back</b> to cancel and come back later.</p>"
        )
        box.addButton("Go Back", QMessageBox.RejectRole)
        select_btn = box.addButton("Select...", QMessageBox.AcceptRole)
        box.setDefaultButton(select_btn)
        box.exec_()

        if box.clickedButton() is not select_btn:
            return None

        if os.name == "nt":
            filt = "Executables (*.exe);;All files (*)"
        else:
            filt = "All files (*)"
        new_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Locate ODA File Converter executable",
            "",
            filt,
        )
        if new_path and os.path.exists(new_path):
            s.setValue(SETTINGS_ODA_PATH, new_path)
            return new_path
        self._flash(
            "ODA File Converter path not set. Cancelled.", Qgis.Warning
        )
        return None

    def _restore_tool(self):
        if self.previous_tool is not None:
            self.iface.mapCanvas().setMapTool(self.previous_tool)
        self.previous_tool = None
        self.map_tool = None

    # --- Workflow steps -----------------------------------------------------
    def start(self):
        if not self._get_visible_vector_layers():
            self._flash("No visible vector layers.", Qgis.Warning)
            return

        oda = self._ensure_oda_path()
        if not oda:
            return
        self._oda_path = oda

        self._flash(
            "Click two opposite corners, or click-drag a box. "
            "Esc or right-click to cancel.",
            Qgis.Info, 6,
        )
        canvas = self.iface.mapCanvas()
        self.previous_tool = canvas.mapTool()
        self.map_tool = BoxMapTool(
            canvas, self._on_box_drawn, self._on_box_cancelled
        )
        canvas.setMapTool(self.map_tool)

    def _on_box_cancelled(self):
        self._restore_tool()
        self._flash("Cancelled.", Qgis.Info)

    def _on_box_drawn(self, rect):
        self._restore_tool()

        if rect.width() == 0 or rect.height() == 0:
            self._flash("Nothing chosen: zero area box.", Qgis.Warning)
            return

        layers = self._get_visible_vector_layers()
        if not layers:
            self._flash("No visible vector layers.", Qgis.Warning)
            return

        project_crs = QgsProject.instance().crs()
        units = project_crs.mapUnits()
        hint = "feet" if units == QgsUnitTypes.DistanceFeet else "meters"

        path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            "Save DWG (coordinates in {})".format(hint),
            "",
            "AutoCAD DWG (*.dwg)",
        )
        if not path:
            self._flash("Save cancelled.", Qgis.Info)
            return
        if not path.lower().endswith(".dwg"):
            path += ".dwg"

        oda = self._oda_path
        if not oda or not os.path.exists(oda):
            self._flash(
                "ODA File Converter path not set. Aborting.", Qgis.Critical
            )
            return

        # --- Synchronous: clip layers and write temp DXF -------------------
        try:
            dxf_dir = self._clip_and_write_dxf(layers, rect, project_crs)
        except Exception as e:
            QgsMessageLog.logMessage(
                "Clip/DXF failed: {}".format(e), PLUGIN_NAME, Qgis.Critical
            )
            self._flash(
                "Failed to prepare DXF: {}".format(e), Qgis.Critical, 8
            )
            return

        if dxf_dir is None:
            self._flash(
                "No features found within the box.", Qgis.Warning
            )
            return

        # --- Background: ODA conversion ------------------------------------
        task = DwgConvertTask(dxf_dir, path, oda)
        task.taskCompleted.connect(
            lambda t=task, p=path: self._on_task_done(t, p, True)
        )
        task.taskTerminated.connect(
            lambda t=task, p=path: self._on_task_done(t, p, False)
        )
        QgsApplication.taskManager().addTask(task)
        self._flash("Exporting in background...", Qgis.Info, 3)

    def _clip_and_write_dxf(self, layers, extent, project_crs):
        """Clip layers to extent, write a DXF to a temp dir, return that dir.

        Returns None if there are no features to export.
        """
        # Build an overlay layer holding the bbox polygon in project CRS
        bbox_geom = QgsGeometry.fromRect(extent)
        bbox_layer = QgsVectorLayer(
            "Polygon?crs={}".format(project_crs.authid()),
            "bbox",
            "memory",
        )
        feat = QgsFeature()
        feat.setGeometry(bbox_geom)
        bbox_layer.dataProvider().addFeatures([feat])
        bbox_layer.updateExtents()

        clipped_layers = []
        for lyr in layers:
            try:
                is_polygon = (
                    lyr.geometryType() == QgsWkbTypes.PolygonGeometry
                )

                # Pass 1: clip the layer normally. For polygons this gives
                # the fill source for HATCH entities; outline strokes will
                # be suppressed via the cloned renderer below. For lines
                # and points, this is the only pass.
                result = processing.run(
                    "native:clip",
                    {
                        "INPUT": lyr,
                        "OVERLAY": bbox_layer,
                        "OUTPUT": "memory:",
                    },
                )
                clipped = result["OUTPUT"]
                if clipped.featureCount() > 0:
                    clipped.setName(lyr.name())
                    try:
                        src_renderer = lyr.renderer()
                        if src_renderer is not None:
                            cloned = src_renderer.clone()
                            self._disable_invisible_symbol_layers(cloned)
                            if is_polygon:
                                self._disable_polygon_stroke(cloned)
                            clipped.setRenderer(cloned)
                    except Exception as e:
                        QgsMessageLog.logMessage(
                            "Renderer clone failed for {}: {}".format(
                                lyr.name(), e
                            ),
                            PLUGIN_NAME, Qgis.Warning,
                        )
                    clipped_layers.append(clipped)

                # Pass 2 (polygons only): convert polygon boundaries to
                # lines first, then clip. Polygons that cross the bbox
                # produce open polylines that stop at the bbox edge
                # instead of closing along it.
                #
                # Pre-filter the source by bbox-intersection using a
                # spatial index (extractbylocation) so polygonstolines
                # only processes nearby polygons instead of every
                # polygon in the layer. Big speedup on wide-area layers.
                if is_polygon:
                    try:
                        subset_result = processing.run(
                            "native:extractbylocation",
                            {
                                "INPUT": lyr,
                                "INTERSECT": bbox_layer,
                                "PREDICATE": [0],
                                "OUTPUT": "memory:",
                            },
                        )
                        subset_layer = subset_result["OUTPUT"]
                        if subset_layer.featureCount() > 0:
                            lines_result = processing.run(
                                "native:polygonstolines",
                                {"INPUT": subset_layer, "OUTPUT": "memory:"},
                            )
                            lines_layer = lines_result["OUTPUT"]
                            clipped_lines_result = processing.run(
                                "native:clip",
                                {
                                    "INPUT": lines_layer,
                                    "OVERLAY": bbox_layer,
                                    "OUTPUT": "memory:",
                                },
                            )
                            clipped_lines = clipped_lines_result["OUTPUT"]
                            if clipped_lines.featureCount() > 0:
                                clipped_lines.setName(lyr.name())
                                clipped_layers.append(clipped_lines)
                    except Exception as e:
                        QgsMessageLog.logMessage(
                            "Boundary line pass failed for {}: {}".format(
                                lyr.name(), e
                            ),
                            PLUGIN_NAME, Qgis.Warning,
                        )
            except Exception as e:
                QgsMessageLog.logMessage(
                    "Skipping {}: {}".format(lyr.name(), e),
                    PLUGIN_NAME, Qgis.Warning,
                )

        if not clipped_layers:
            return None

        tmpdir = tempfile.mkdtemp(prefix="cliptodwg_")
        try:
            dxf_path = os.path.join(tmpdir, "out.dxf")

            dxf = QgsDxfExport()
            dxf.addLayers([QgsDxfExport.DxfLayer(l) for l in clipped_layers])
            dxf.setSymbologyExport(QgsDxfExport.SymbolLayerSymbology)
            try:
                dxf.setSymbologyScale(self.iface.mapCanvas().scale())
            except Exception:
                pass
            dxf.setExtent(extent)
            dxf.setDestinationCrs(project_crs)

            f = QFile(dxf_path)
            if not f.open(QIODevice.WriteOnly):
                raise RuntimeError("Could not open temp DXF for writing.")

            try:
                res = dxf.writeToFile(f, "UTF-8")
            finally:
                f.close()

            # QgsDxfExport.ExportResult.Success == 0 in QGIS 3.x
            if res != 0:
                raise RuntimeError(
                    "QgsDxfExport.writeToFile returned error {}".format(res)
                )
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

        try:
            self._drop_invisible_hatches(dxf_path)
        except Exception as e:
            QgsMessageLog.logMessage(
                "Invisible hatch drop failed: {}".format(e),
                PLUGIN_NAME, Qgis.Warning,
            )

        try:
            self._force_bylayer(dxf_path)
        except Exception as e:
            QgsMessageLog.logMessage(
                "ByLayer scrub failed: {}".format(e),
                PLUGIN_NAME, Qgis.Warning,
            )

        return tmpdir

    def _disable_polygon_stroke(self, renderer):
        """Suppress outline strokes on polygon fill symbol layers so the
        clipped polygon only emits HATCH (no closed polyline outline along
        the bbox edge). Boundary lines come from the separate boundary
        pass.
        """
        try:
            ctx = QgsRenderContext()
            symbols = renderer.symbols(ctx)
        except Exception:
            return
        for symbol in symbols:
            if symbol is None:
                continue
            try:
                count = symbol.symbolLayerCount()
            except Exception:
                continue
            for i in range(count):
                try:
                    sl = symbol.symbolLayer(i)
                except Exception:
                    continue
                if sl is None:
                    continue
                if hasattr(sl, "setStrokeStyle"):
                    try:
                        sl.setStrokeStyle(Qt.NoPen)
                    except Exception:
                        pass

    def _disable_invisible_symbol_layers(self, renderer):
        """Walk a renderer's symbols and disable any symbol layer that is
        eye-toggled off, has fully transparent colour, or uses NoBrush
        fill style. QgsDxfExport skips disabled symbol layers, so this
        suppresses HATCH output for features the user has hidden.
        """
        try:
            ctx = QgsRenderContext()
            symbols = renderer.symbols(ctx)
        except Exception:
            return
        for symbol in symbols:
            if symbol is None:
                continue
            try:
                count = symbol.symbolLayerCount()
            except Exception:
                continue
            for i in range(count):
                try:
                    sl = symbol.symbolLayer(i)
                except Exception:
                    continue
                if sl is None:
                    continue
                try:
                    if not sl.enabled():
                        continue
                except Exception:
                    pass
                invisible = False
                try:
                    c = sl.color()
                    if c is not None and c.alpha() == 0:
                        invisible = True
                except Exception:
                    pass
                try:
                    if hasattr(sl, "brushStyle"):
                        # Qt.NoBrush == 0
                        if int(sl.brushStyle()) == 0:
                            invisible = True
                except Exception:
                    pass
                try:
                    if hasattr(sl, "fillColor"):
                        fc = sl.fillColor()
                        if fc is not None and fc.alpha() == 0:
                            invisible = True
                except Exception:
                    pass
                if invisible:
                    try:
                        sl.setEnabled(False)
                    except Exception:
                        pass

    def _drop_invisible_hatches(self, dxf_path):
        """Remove HATCH entities whose DXF transparency (group code 440)
        indicates alpha byte = 0 (fully transparent). Preserves partially
        transparent hatches.
        """
        with open(dxf_path, "rb") as fh:
            raw = fh.read()
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        lines = raw.split(newline)

        out = []
        i = 0
        n = len(lines)
        while i < n - 1:
            code = lines[i].strip().decode("ascii", errors="replace")
            value = lines[i + 1].strip().decode("ascii", errors="replace")

            if code == "0" and value == "HATCH":
                buf = [lines[i], lines[i + 1]]
                j = i + 2
                alpha = None
                while j < n - 1:
                    ec = lines[j].strip().decode("ascii", errors="replace")
                    if ec == "0":
                        break
                    ev = lines[j + 1].strip().decode("ascii", errors="replace")
                    if ec == "440":
                        try:
                            alpha = int(ev) & 0xFF
                        except ValueError:
                            pass
                    buf.append(lines[j])
                    buf.append(lines[j + 1])
                    j += 2

                if alpha == 0:
                    # Skip writing this entity entirely
                    pass
                else:
                    out.extend(buf)
                i = j
                continue

            out.append(lines[i])
            out.append(lines[i + 1])
            i += 2

        if i == n - 1:
            out.append(lines[i])

        with open(dxf_path, "wb") as fh:
            fh.write(newline.join(out))

    def _force_bylayer(self, dxf_path):
        """Strip per-entity color/linetype/lineweight overrides in ENTITIES
        and BLOCKS sections so non-hatch entities default to ByLayer.
        HATCH entities are left untouched so fill colour, pattern, and
        transparency (group code 440) survive. Polyline width codes are
        also stripped so polylines render at width 0.
        """
        # Group codes scrubbed from non-hatch entities:
        # 62 color index, 420 true color, 430 color name,
        # 440 transparency, 6 linetype, 370 lineweight
        scrub = {"62", "420", "430", "440", "6", "370"}
        keep_types = {"HATCH"}
        # Type-specific scrub: codes whose meaning depends on entity type.
        # LWPOLYLINE: 43 constant width, 40 start width, 41 end width.
        # POLYLINE: 40 start width, 41 end width (per vertex via VERTEX).
        # VERTEX (sub-entity of POLYLINE): 40 start width, 41 end width.
        type_specific_scrub = {
            "LWPOLYLINE": {"43", "40", "41"},
            "POLYLINE": {"40", "41"},
            "VERTEX": {"40", "41"},
        }

        with open(dxf_path, "rb") as fh:
            raw = fh.read()
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        lines = raw.split(newline)

        out = []
        section_pending = False
        in_scrub_section = False
        current_entity = None

        i = 0
        n = len(lines)
        while i < n - 1:
            code = lines[i].strip().decode("ascii", errors="replace")
            value = lines[i + 1].strip().decode("ascii", errors="replace")

            if code == "0" and value == "SECTION":
                section_pending = True
                current_entity = None
            elif section_pending and code == "2":
                in_scrub_section = value in ("ENTITIES", "BLOCKS")
                section_pending = False
            elif code == "0" and value == "ENDSEC":
                in_scrub_section = False
                current_entity = None
            elif code == "0" and in_scrub_section:
                current_entity = value

            if in_scrub_section and current_entity not in keep_types:
                if code in scrub:
                    i += 2
                    continue
                extra = type_specific_scrub.get(current_entity)
                if extra and code in extra:
                    i += 2
                    continue

            out.append(lines[i])
            out.append(lines[i + 1])
            i += 2

        # Trailing line if odd count
        if i == n - 1:
            out.append(lines[i])

        with open(dxf_path, "wb") as fh:
            fh.write(newline.join(out))

    def _on_task_done(self, task, path, ok):
        if ok and not task.error:
            self._flash("Saved: {}".format(path), Qgis.Success, 6)
        else:
            self._flash(
                "Export failed: {}".format(task.error or "unknown error"),
                Qgis.Critical, 8,
            )
