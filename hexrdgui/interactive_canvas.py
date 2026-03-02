from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from PySide6.QtCore import QRectF, QTimer, Qt, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from matplotlib.axes import Axes

if TYPE_CHECKING:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPaintEvent, QMouseEvent, QResizeEvent, QWheelEvent

# Minimum drag distance (in pixels) before a left-click becomes a pan
_PAN_THRESHOLD = 5

# Zoom factor per scroll step
_ZOOM_BASE = 1.15

# Device-pixel inset when extracting axis content to exclude spine lines
_SPINE_INSET = 2


class InteractiveCanvasMixin:
    """Mixin for matplotlib FigureCanvasQTAgg providing fast scroll-zoom and
    left-click pan via Qt pixmap preview with debounced matplotlib redraw.

    Must be listed first in MRO so its event handlers override FigureCanvas.
    Call ``_init_interactive()`` at the end of the host class ``__init__``.
    """

    def _init_interactive(self) -> None:
        self._interaction_active: bool = False
        self._cached_pixmap: QPixmap | None = None
        self._pending_limits: dict[
            Axes, tuple[tuple[float, float], tuple[float, float]]
        ] = {}
        # Limits at the moment the interaction started (for sub-pixmap transform)
        self._orig_limits: dict[
            Axes, tuple[tuple[float, float], tuple[float, float]]
        ] = {}

        # Per-axis data populated during _begin_interaction
        self._axis_widget_rects: dict[Axes, QRectF] = {}
        self._axis_content_pixmaps: dict[Axes, QPixmap] = {}
        self._axis_clip_rects: dict[Axes, QRectF] = {}

        # Full-data QPixmaps for PyQtGraph-like rendering (image axes only)
        self._axis_data_pixmaps: dict[Axes, QPixmap] = {}
        # (left, right, bottom, top), origin, img_w, img_h
        self._axis_img_info: dict[
            Axes, tuple[tuple[float, float, float, float], str, int, int]
        ] = {}

        # Debounce timer: fires once after interaction stops
        self._finalize_timer: QTimer = QTimer(self)  # type: ignore[arg-type]
        self._finalize_timer.setSingleShot(True)
        self._finalize_timer.setInterval(500)
        self._finalize_timer.timeout.connect(self._finalize_interaction)

        # Pan state
        self._pan_active: bool = False
        self._pan_start_pos: QPointF | None = None
        self._pan_target_ax: Axes | None = None

        # Potential pan (left-click before threshold)
        self._potential_pan_start: QPointF | None = None
        self._potential_pan_ax: Axes | None = None

        # Whether a wheel zoom has been performed — panning is only
        # allowed after the user has zoomed into the canvas.
        self._zoom_has_occurred: bool = False

        # Nav toolbar reference (set externally by image_tab_widget)
        self._nav_toolbar = None

    # ------------------------------------------------------------------
    # Axis lookup helpers
    # ------------------------------------------------------------------

    def _axes_under_cursor(self, pos: QPoint) -> Axes | None:
        """Return the matplotlib Axes under the given widget-coordinate pos."""
        dpr = self.devicePixelRatioF()
        display_x = pos.x() * dpr
        display_y = self.figure.bbox.height - pos.y() * dpr

        for ax in self.figure.get_axes():
            bbox = ax.get_window_extent()
            if bbox.contains(display_x, display_y):
                return ax
        return None

    def _redirect_to_main_axis(self, ax: Axes) -> Axes:
        """If *ax* is the azimuthal lineout or WPPF difference axis, redirect
        to the main polar image axis so that zoom/pan operates on the image."""
        canvas = self  # type: ignore[assignment]
        if (
            hasattr(canvas, 'azimuthal_integral_axis')
            and ax is canvas.azimuthal_integral_axis
        ):
            return self._find_main_axis() or ax
        if (
            hasattr(canvas, 'wppf_difference_axis')
            and ax is canvas.wppf_difference_axis
        ):
            return self._find_main_axis() or ax
        return ax

    def _find_main_axis(self) -> Axes | None:
        """Return the primary image axis (``self.axis`` when it exists)."""
        if hasattr(self, 'axis'):
            return self.axis  # type: ignore[attr-defined]
        axes = self.figure.get_axes()
        return axes[0] if axes else None

    def _get_linked_axes(self, ax: Axes) -> list[Axes]:
        """Return *ax* plus all axes sharing the same x or y grouping."""
        linked: set[Axes] = {ax}
        for other in self.figure.get_axes():
            if other is ax:
                continue
            if ax.get_shared_x_axes().joined(ax, other):
                linked.add(other)
            if ax.get_shared_y_axes().joined(ax, other):
                linked.add(other)
        return list(linked)

    def _toolbar_mode_active(self) -> bool:
        """Return True if the navigation toolbar is in pan or zoom mode."""
        for ax in self.figure.get_axes():
            if ax.get_navigate_mode() is not None:
                return True
        return False

    # ------------------------------------------------------------------
    # Axis rect / pixmap helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _axis_bg_color(ax: Axes) -> QColor:
        """Return the axis facecolor as a QColor."""
        fc = ax.get_facecolor()  # (r, g, b, a) floats 0-1
        return QColor.fromRgbF(fc[0], fc[1], fc[2], fc[3])

    def _build_axis_data(self) -> None:
        """Compute widget rects, extract sub-pixmaps, and build full-data
        QPixmaps for every axis.  Called once at the start of an interaction."""
        assert self._cached_pixmap is not None
        dpr = self.devicePixelRatioF()
        fig_h = self.figure.bbox.height
        inset = _SPINE_INSET
        inset_lp = inset / dpr

        self._axis_widget_rects.clear()
        self._axis_content_pixmaps.clear()
        self._axis_clip_rects.clear()
        self._axis_data_pixmaps.clear()
        self._axis_img_info.clear()

        for ax in self.figure.get_axes():
            bbox = ax.get_window_extent()

            wx = bbox.x0 / dpr
            wy = (fig_h - bbox.y1) / dpr
            ww = bbox.width / dpr
            wh = bbox.height / dpr
            full_rect = QRectF(wx, wy, ww, wh)
            self._axis_widget_rects[ax] = full_rect

            self._axis_clip_rects[ax] = full_rect.adjusted(
                inset_lp, inset_lp, -inset_lp, -inset_lp
            )

            # Extract sub-pixmap of axis interior (for overlays / non-image axes)
            px = int(round(bbox.x0)) + inset
            py = int(round(fig_h - bbox.y1)) + inset
            pw = int(round(bbox.width)) - 2 * inset
            ph = int(round(bbox.height)) - 2 * inset

            if pw > 0 and ph > 0:
                sub = self._cached_pixmap.copy(px, py, pw, ph)
                sub.setDevicePixelRatio(self._cached_pixmap.devicePixelRatio())
                self._axis_content_pixmaps[ax] = sub

            # Build full-data QPixmap from the AxesImage (if any)
            self._build_image_pixmap(ax)

    def _build_image_pixmap(self, ax: Axes) -> None:
        """Colormap the full numpy data behind *ax*'s AxesImage into a
        QPixmap for PyQtGraph-like rendering at any zoom level."""
        images = ax.get_images()
        if not images:
            return
        im = images[0]
        data = im.get_array()
        if data is None or data.size == 0:
            return

        try:
            rgba = im.to_rgba(data, bytes=True)  # (h, w, 4) uint8
            rgba = np.ascontiguousarray(rgba)
        except Exception:
            return

        h, w = rgba.shape[:2]
        # Use tobytes() so the QImage owns a copy of the data
        raw = rgba.tobytes()
        qimg = QImage(raw, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self._axis_data_pixmaps[ax] = QPixmap.fromImage(qimg)

        extent = im.get_extent()  # (left, right, bottom, top)
        origin = getattr(im, 'origin', 'upper')
        self._axis_img_info[ax] = (extent, origin, w, h)

    # ------------------------------------------------------------------
    # Transform computation
    # ------------------------------------------------------------------

    def _image_to_widget_transform(
        self,
        ax: Axes,
        xlim: tuple[float, float],
        ylim: tuple[float, float],
    ) -> QTransform:
        """Compute QTransform mapping image pixels -> widget coords."""
        extent, origin, img_w, img_h = self._axis_img_info[ax]
        left, right, bottom, top = extent
        rect = self._axis_widget_rects[ax]
        wx, wy, ww, wh = rect.x(), rect.y(), rect.width(), rect.height()

        vx = xlim[1] - xlim[0]
        vy = ylim[1] - ylim[0]
        if vx == 0 or vy == 0 or img_w == 0 or img_h == 0:
            return QTransform()

        sx = (right - left) * ww / (img_w * vx)
        tx = wx + (left - xlim[0]) * ww / vx

        # QImage row 0 is top.
        #   origin='upper' -> row 0 = top,   row h = bottom
        #   origin='lower' -> row 0 = bottom, row h = top
        y_start = top if origin == 'upper' else bottom
        y_end = bottom if origin == 'upper' else top

        # Widget y increases downward, but data y at ylim[0] maps to the
        # BOTTOM of the axes (wy + wh) and ylim[1] to the TOP (wy).
        # So: widget_y = wy + wh - (data_y - ylim[0]) * wh / vy
        ty = wy + wh - (y_start - ylim[0]) * wh / vy
        sy = -(y_end - y_start) * wh / (img_h * vy)

        t = QTransform()
        t.translate(tx, ty)
        t.scale(sx, sy)
        return t

    def _content_to_widget_transform(
        self,
        ax: Axes,
        new_xlim: tuple[float, float],
        new_ylim: tuple[float, float],
    ) -> QTransform:
        """Compute QTransform that places the captured sub-pixmap at the
        correct position for the new data limits."""
        orig_xlim, orig_ylim = self._orig_limits[ax]
        rect = self._axis_widget_rects[ax]
        wx, wy, ww, wh = rect.x(), rect.y(), rect.width(), rect.height()

        new_vx = new_xlim[1] - new_xlim[0]
        new_vy = new_ylim[1] - new_ylim[0]
        if new_vx == 0 or new_vy == 0:
            return QTransform()

        # Scale: ratio of original data range to new data range
        sx = (orig_xlim[1] - orig_xlim[0]) / new_vx
        sy = (orig_ylim[1] - orig_ylim[0]) / new_vy

        # The sub-pixmap was extracted with _SPINE_INSET device-pixel inset,
        # so pixel (0,0) corresponds to widget (wx + inset_lp, wy + inset_lp)
        # rather than the axis corner (wx, wy).  The inset_lp offset in the
        # original view maps to inset_lp * scale in the new view.
        inset_lp = _SPINE_INSET / self.devicePixelRatioF()

        new_ox = (wx + (orig_xlim[0] - new_xlim[0]) / new_vx * ww
                  + inset_lp * sx)
        new_oy = (wy + wh - (orig_ylim[1] - new_ylim[0]) / new_vy * wh
                  + inset_lp * sy)

        t = QTransform()
        t.translate(new_ox, new_oy)
        t.scale(sx, sy)
        return t

    # ------------------------------------------------------------------
    # Interaction lifecycle
    # ------------------------------------------------------------------

    def _begin_interaction(self, ax: Axes) -> None:
        """Capture pixmap and seed pending limits for preview mode."""
        if self._interaction_active:
            return
        self._interaction_active = True
        self._cached_pixmap = self.grab()

        # Push the pre-interaction state so the toolbar "home" button
        # always returns to the view before any interactive zoom/pan.
        if self._nav_toolbar is not None:
            self._nav_toolbar.push_current()

        self._build_axis_data()

        # Seed original and pending limits
        self._orig_limits.clear()
        self._pending_limits.clear()
        for a in self.figure.get_axes():
            lims = (
                tuple(a.get_xlim()),  # type: ignore[assignment]
                tuple(a.get_ylim()),  # type: ignore[assignment]
            )
            self._orig_limits[a] = lims
            self._pending_limits[a] = lims

    def _reset_zoom_flag(self) -> None:
        """Reset the zoom flag so panning is disabled until the next zoom."""
        self._zoom_has_occurred = False

    def _invalidate_interaction_cache(self) -> None:
        """Cancel any active interaction and reset state."""
        self._finalize_timer.stop()
        self._interaction_active = False
        self._cached_pixmap = None
        self._pending_limits.clear()
        self._orig_limits.clear()
        self._axis_widget_rects.clear()
        self._axis_content_pixmaps.clear()
        self._axis_clip_rects.clear()
        self._axis_data_pixmaps.clear()
        self._axis_img_info.clear()
        self._pan_active = False
        self._pan_start_pos = None
        self._pan_target_ax = None
        self._potential_pan_start = None
        self._potential_pan_ax = None
        self._zoom_has_occurred = False

    def _finalize_interaction(self) -> None:
        """Apply pending limits, push nav stack, and trigger a single redraw."""
        if not self._interaction_active:
            return

        for ax, (xlim, ylim) in self._pending_limits.items():
            ax.set_xlim(xlim)
            ax.set_ylim(ylim)

        if self._nav_toolbar is not None:
            self._nav_toolbar.push_current()

        self._interaction_active = False
        self._cached_pixmap = None
        self._pending_limits.clear()
        self._orig_limits.clear()
        self._axis_widget_rects.clear()
        self._axis_content_pixmaps.clear()
        self._axis_clip_rects.clear()
        self._axis_data_pixmaps.clear()
        self._axis_img_info.clear()
        self._pan_active = False
        self._pan_start_pos = None
        self._pan_target_ax = None

        self.draw_idle()

    # ------------------------------------------------------------------
    # Zoom math
    # ------------------------------------------------------------------

    def _apply_zoom_to_limits(self, ax: Axes, pos: QPoint, scale: float) -> None:
        """Compute new data-space limits for *ax* zoomed by *scale* centered
        on widget position *pos*."""
        bbox = ax.get_window_extent()
        dpr = self.devicePixelRatioF()
        display_x = pos.x() * dpr
        display_y = self.figure.bbox.height - pos.y() * dpr

        xlim, ylim = self._pending_limits.get(
            ax, (tuple(ax.get_xlim()), tuple(ax.get_ylim()))
        )
        x0, x1 = xlim
        y0, y1 = ylim

        rel_x = (display_x - bbox.x0) / bbox.width if bbox.width else 0.5
        rel_y = (display_y - bbox.y0) / bbox.height if bbox.height else 0.5
        rel_x = max(0.0, min(1.0, rel_x))
        rel_y = max(0.0, min(1.0, rel_y))

        y_inverted = y0 > y1
        if y_inverted:
            y0, y1 = y1, y0
            rel_y = 1.0 - rel_y

        data_x = x0 + rel_x * (x1 - x0)
        data_y = y0 + rel_y * (y1 - y0)

        new_xw = (x1 - x0) / scale
        new_yh = (y1 - y0) / scale

        new_x0 = data_x - rel_x * new_xw
        new_x1 = data_x + (1.0 - rel_x) * new_xw
        new_y0 = data_y - rel_y * new_yh
        new_y1 = data_y + (1.0 - rel_y) * new_yh

        if y_inverted:
            new_y0, new_y1 = new_y1, new_y0

        new_xlim = (new_x0, new_x1)
        new_ylim = (new_y0, new_y1)

        for linked in self._get_linked_axes(ax):
            old_xlim, old_ylim = self._pending_limits.get(
                linked, (tuple(linked.get_xlim()), tuple(linked.get_ylim()))
            )
            lx = new_xlim if ax.get_shared_x_axes().joined(ax, linked) else old_xlim
            ly = new_ylim if ax.get_shared_y_axes().joined(ax, linked) else old_ylim
            self._pending_limits[linked] = (lx, ly)

        self._pending_limits[ax] = (new_xlim, new_ylim)

    # ------------------------------------------------------------------
    # Pan math
    # ------------------------------------------------------------------

    def _apply_pan_to_limits(
        self, ax: Axes, dx_widget: float, dy_widget: float
    ) -> None:
        """Compute new data-space limits for *ax* panned by widget-pixel
        displacement (*dx_widget*, *dy_widget*)."""
        bbox = ax.get_window_extent()
        dpr = self.devicePixelRatioF()

        xlim, ylim = self._pending_limits.get(
            ax, (tuple(ax.get_xlim()), tuple(ax.get_ylim()))
        )

        dx_data = (
            -dx_widget * dpr * (xlim[1] - xlim[0]) / bbox.width if bbox.width else 0
        )
        dy_data = (
            dy_widget * dpr * (ylim[1] - ylim[0]) / bbox.height if bbox.height else 0
        )

        new_xlim = (xlim[0] + dx_data, xlim[1] + dx_data)
        new_ylim = (ylim[0] + dy_data, ylim[1] + dy_data)

        for linked in self._get_linked_axes(ax):
            old_xlim, old_ylim = self._pending_limits.get(
                linked, (tuple(linked.get_xlim()), tuple(linked.get_ylim()))
            )
            lx = new_xlim if ax.get_shared_x_axes().joined(ax, linked) else old_xlim
            ly = new_ylim if ax.get_shared_y_axes().joined(ax, linked) else old_ylim
            self._pending_limits[linked] = (lx, ly)

        self._pending_limits[ax] = (new_xlim, new_ylim)

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        ax = self._axes_under_cursor(pos)
        if ax is None:
            super().wheelEvent(event)  # type: ignore[misc]
            return

        ax = self._redirect_to_main_axis(ax)

        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)  # type: ignore[misc]
            return

        steps = delta / 120.0
        scale = _ZOOM_BASE**steps

        if not self._interaction_active:
            self._begin_interaction(ax)

        self._zoom_has_occurred = True

        self._apply_zoom_to_limits(ax, pos, scale)

        self.update()
        self._finalize_timer.start()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._toolbar_mode_active()
            and self._zoom_has_occurred
        ):
            pos = event.position()
            ax = self._axes_under_cursor(pos.toPoint())
            if ax is not None:
                ax = self._redirect_to_main_axis(ax)
                self._potential_pan_start = pos
                self._potential_pan_ax = ax

        super().mousePressEvent(event)  # type: ignore[misc]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._potential_pan_start is not None
            and not self._pan_active
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            dx = event.position().x() - self._potential_pan_start.x()
            dy = event.position().y() - self._potential_pan_start.y()
            if math.hypot(dx, dy) > _PAN_THRESHOLD:
                self._pan_active = True
                self._pan_target_ax = self._potential_pan_ax
                self._pan_start_pos = event.position()
                if not self._interaction_active:
                    self._begin_interaction(self._pan_target_ax)

        if self._pan_active and self._pan_start_pos is not None:
            current = event.position()
            dx = current.x() - self._pan_start_pos.x()
            dy = current.y() - self._pan_start_pos.y()

            self._apply_pan_to_limits(self._pan_target_ax, dx, dy)

            self._pan_start_pos = current
            self.update()
            self._finalize_timer.start()
            event.accept()
            return

        super().mouseMoveEvent(event)  # type: ignore[misc]

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._pan_active:
                self._pan_active = False
                self._pan_start_pos = None
                self._pan_target_ax = None
                self._potential_pan_start = None
                self._potential_pan_ax = None
                self._finalize_timer.stop()
                self._finalize_interaction()
                event.accept()
                return
            else:
                self._potential_pan_start = None
                self._potential_pan_ax = None

        super().mouseReleaseEvent(event)  # type: ignore[misc]

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._interaction_active and self._cached_pixmap is not None:
            painter = QPainter(self)

            # 1) Static background — axes, ticks, labels, spines.
            painter.drawPixmap(0, 0, self._cached_pixmap)

            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            # 2) For each axis, redraw content at the new limits.
            for ax in self._axis_clip_rects:
                clip_rect = self._axis_clip_rects[ax]
                has_image = ax in self._axis_data_pixmaps
                has_overlay = ax in self._axis_content_pixmaps

                if not has_image and not has_overlay:
                    continue

                xlim, ylim = self._pending_limits.get(
                    ax,
                    (tuple(ax.get_xlim()), tuple(ax.get_ylim())),
                )

                painter.save()
                painter.setClipRect(clip_rect)
                painter.fillRect(clip_rect, self._axis_bg_color(ax))

                # a) Full image data with exact data->widget transform
                if has_image:
                    img_t = self._image_to_widget_transform(ax, xlim, ylim)
                    painter.setTransform(img_t)
                    painter.drawPixmap(0, 0, self._axis_data_pixmaps[ax])
                    painter.resetTransform()
                    painter.setClipRect(clip_rect)

                # b) Captured overlay sub-pixmap, repositioned using the
                #    same limit-based math so it aligns with the image.
                if has_overlay:
                    content_t = self._content_to_widget_transform(ax, xlim, ylim)
                    painter.setTransform(content_t)
                    painter.drawPixmap(QPointF(0, 0), self._axis_content_pixmaps[ax])

                painter.restore()

            painter.end()
        else:
            super().paintEvent(event)  # type: ignore[misc]

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        self._invalidate_interaction_cache()
        super().resizeEvent(event)  # type: ignore[misc]
