from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from matplotlib import patches
from matplotlib.axes import Axes
from matplotlib.backend_bases import KeyEvent, MouseEvent
from matplotlib.path import Path
from matplotlib.transforms import Affine2D

from hexrdgui.constants import KEY_ROTATE_ANGLE_FINE, KEY_TRANSLATE_DELTA, ViewType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import has_nan
from hexrdgui.utils.matplotlib import remove_artist
from hexrdgui.utils.polygon import polygon_to_mask

if TYPE_CHECKING:
    from hexrd.instrument import HEDMInstrument
    from hexrdgui.image_canvas import ImageCanvas


class InteractiveTemplate:
    def __init__(
        self,
        canvas: ImageCanvas,
        detector: str,
        axes: Axes | None = None,
        instrument: HEDMInstrument | None = None,
    ) -> None:
        self.current_canvas = canvas
        self.img: np.ndarray | None = None
        self.shape: patches.Polygon | None = None
        self.press: tuple[np.ndarray, float, float] | None = None
        self.total_rotation = 0.0
        self.patches: list[patches.Patch] = []
        self.shape_styles: list[dict[str, Any]] = []
        self.translation: list[float] = [0, 0]
        self.complete = False
        self.event_key: str | None = None
        self.detector = detector
        self.instrument = instrument
        self._static = True
        self.axis_image = axes.get_images()[0] if axes else canvas.axes_images[0]
        self._key_angle = KEY_ROTATE_ANGLE_FINE

        self.button_press_cid: int | None = None
        self.button_release_cid: int | None = None
        self.motion_cid: int | None = None
        self.key_press_cid: int | None = None
        self.button_drag_cid: int | None = None

    @property
    def axis(self) -> Axes:
        if not self.current_canvas.raw_axes:
            return self.current_canvas.axis

        for axes in self.current_canvas.raw_axes.values():
            if axes.get_title() == self.detector:
                return axes

        return list(self.current_canvas.raw_axes.values())[0]

    @property
    def static_mode(self) -> bool:
        return self._static

    @static_mode.setter
    def static_mode(self, mode: bool) -> None:
        if mode == self._static:
            return

        self._static = mode
        self.update_style(color='black')
        if not mode:
            self.connect_translate_rotate()
            self.update_style(color='red')

    @property
    def key_rotation_angle(self) -> float:
        return self._key_angle

    @key_rotation_angle.setter
    def key_rotation_angle(self, angle: float | None = None) -> None:
        if angle is None:
            angle = KEY_ROTATE_ANGLE_FINE
        self._key_angle = angle

    def update_image(self, img: np.ndarray) -> None:
        self.img = img

    def rotate_shape(self, angle: float) -> None:
        assert self.shape is not None
        angle = np.radians(angle)
        self.rotate_template(self.shape.xy, angle)
        self.redraw()

    def create_polygon(self, verts: np.ndarray, **polygon_kwargs: Any) -> None:
        self.complete = False
        self.shape = patches.Polygon(verts, **polygon_kwargs)
        if has_nan(verts):
            # This template contains more than one polygon and the last point
            # should not be connected to the first. See Tardis IP for example.
            self.shape.set_closed(False)
        self.shape_styles.append(polygon_kwargs)
        self.update_position()
        self.connect_translate_rotate()
        self.axis.add_patch(self.shape)
        self.redraw()

    def update_style(
        self,
        style: str | None = None,
        width: int | None = None,
        color: str | None = None,
    ) -> None:
        if not self.shape:
            return

        if style:
            self.shape.set_linestyle(style)
        if width:
            self.shape.set_linewidth(width)
        if color:
            self.shape.set_edgecolor(color)
        self.shape_styles[-1] = {
            'line': self.shape.get_linestyle(),
            'width': self.shape.get_linewidth(),
            'color': self.shape.get_edgecolor(),
        }
        self.shape.set_fill(False)
        self.redraw()

    def update_position(self) -> None:
        pos = None
        if self.instrument is not None:
            pos = HexrdConfig().boundary_position(self.instrument, self.detector)
        if pos is None:
            self.center = self.get_midpoint()
        else:
            assert self.shape is not None
            dx, dy = pos.get('translation', [0, 0])
            self.translation = [dx, dy]
            self.translate_template(dx, dy)
            self.total_rotation = pos['angle']
            self.rotate_template(self.shape.xy, pos['angle'])
        if self.instrument == 'PXRDIP':
            self.rotate_shape(angle=90)

    @property
    def template(self) -> Any:
        return self.shape

    @property
    def masked_image(self) -> tuple[np.ndarray | None, np.ndarray]:
        mask = self.mask()
        return self.img, mask

    @property
    def bounds(self) -> np.ndarray:
        assert self.shape is not None
        l, r, b, t = self.axis_image.get_extent()
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return np.array(
            [
                max(np.floor(y0), t),
                min(np.ceil(y1), b),
                max(np.floor(x0), l),
                min(np.ceil(x1), r),
            ]
        ).astype(int)

    def cropped_image(self, height: int, width: int) -> np.ndarray:
        assert self.img is not None
        assert self.shape is not None
        y0, y1, x0, x1 = self.bounds
        y1 = y0 + height if height else y1
        x1 = x0 + width if width else x1
        self.img = self.img[y0:y1, x0:x1]
        self.cropped_shape = self.shape.xy - np.array([x0, y0])
        return self.img

    @property
    def rotation(self) -> float:
        return self.total_rotation

    def clear(self) -> None:
        if self.shape is not None and self.shape in self.axis.patches:
            remove_artist(self.shape)
            self.redraw()
        self.total_rotation = 0.0

    def save_boundary(self, color: str) -> None:
        assert self.shape is not None
        if self.shape in self.axis.patches:
            self.shape.set_linestyle('--')
            self.redraw()

    def toggle_boundaries(self, show: bool) -> None:
        if show:
            for patch, style in zip(self.patches, self.shape_styles):
                shape = patches.Polygon(
                    patch.xy,  # type: ignore[attr-defined]
                    fill=False,
                    ls='--',
                    lw=style['width'],
                    color=style['color'],
                )
                if has_nan(patch.xy):  # type: ignore[attr-defined]
                    # This template contains more than one polygon and the last point
                    # should not be connected to the first. See Tardis IP for example.
                    shape.set_closed(False)
                self.axis.add_patch(shape)
            if self.shape:
                last_patch = self.axis.patches[-1]
                assert isinstance(last_patch, patches.Polygon)
                self.shape = last_patch
                remove_artist(self.shape)
                self.shape.set_linestyle(self.shape_styles[-1]['line'])
                self.axis.add_patch(self.shape)
                self.connect_translate_rotate()
            self.redraw()
        else:
            if self.shape:
                self.disconnect()
            self.patches = [p for p in self.axis.patches]
        self.redraw()

    def disconnect(self) -> None:
        if self.button_press_cid is not None:
            self.current_canvas.mpl_disconnect(self.button_press_cid)
        if self.button_release_cid is not None:
            self.current_canvas.mpl_disconnect(self.button_release_cid)
        if self.motion_cid is not None:
            self.current_canvas.mpl_disconnect(self.motion_cid)
        if self.key_press_cid is not None:
            self.current_canvas.mpl_disconnect(self.key_press_cid)
        if self.button_drag_cid is not None:
            self.current_canvas.mpl_disconnect(self.button_drag_cid)

    def completed(self) -> None:
        self.disconnect()
        self.img = None
        self.shape = None
        self.press = None
        self.total_rotation = 0.0
        self.complete = True

    def mask(self) -> np.ndarray:
        assert self.img is not None
        col, row = self.cropped_shape.T
        col_nans = np.where(np.isnan(col))[0]
        row_nans = np.where(np.isnan(row))[0]
        cols = np.split(col, col_nans)
        rows = np.split(row, row_nans)
        master_mask = np.zeros(self.img.shape, dtype=bool)
        for c, r in zip(cols, rows):
            c = c[~np.isnan(c)]
            r = r[~np.isnan(r)]
            mask = ~polygon_to_mask(np.vstack([c, r]).T, self.img.shape)
            master_mask = np.logical_xor(master_mask, mask)
        self.img[~master_mask] = 0
        return master_mask

    def get_paths(self) -> list[Path]:
        assert self.shape is not None
        all_paths = []
        points: list[np.ndarray] = []
        codes: list[int] = []
        for coords in self.shape.get_path().vertices[:-1]:  # type: ignore[union-attr, index]
            if np.isnan(coords).any():
                codes[0] = int(Path.MOVETO)
                all_paths.append(Path(points, codes))  # type: ignore[arg-type]
                codes = []
                points = []
            else:
                codes.append(int(Path.LINETO))
                points.append(coords)  # type: ignore[arg-type]
        codes[0] = int(Path.MOVETO)
        all_paths.append(Path(points, codes))  # type: ignore[arg-type]

        return all_paths

    def redraw(self) -> None:
        self.current_canvas.draw_idle()

    def scale_template(self, sx: int = 1, sy: int = 1) -> None:
        assert self.shape is not None
        xy = self.shape.xy
        # Scale the shape
        scaled_xy = Affine2D().scale(sx, sy).transform(xy)
        self.shape.set_xy(scaled_xy)

        # Translate the shape back to where it was
        diff = np.array(self.center) - np.array(self.get_midpoint())
        new_xy = scaled_xy + diff
        self.shape.set_xy(new_xy)
        self.redraw()

    def on_press(self, event: MouseEvent) -> None:
        if self.static_mode:
            return

        self.event_key = event.key
        if event.key is None:
            self.on_press_translate(event)
        elif event.key == 'shift':
            self.on_press_rotate(event)

    def on_release(self, event: MouseEvent) -> None:
        if self.event_key is None:
            self.on_translate_release(event)
        elif self.event_key == 'shift':
            self.on_rotate_release(event)

    def on_key(self, event: KeyEvent) -> None:
        if self.static_mode:
            return

        if event.key is not None and 'shift' in event.key:
            self.on_key_rotate(event)
        else:
            self.on_key_translate(event)

    def connect_translate_rotate(self) -> None:
        if self.static_mode:
            return

        self.disconnect()

        self.button_press_cid = self.current_canvas.mpl_connect(
            'button_press_event', self.on_press  # type: ignore[arg-type]
        )
        self.button_release_cid = self.current_canvas.mpl_connect(
            'button_release_event', self.on_release  # type: ignore[arg-type]
        )
        self.motion_cid = self.current_canvas.mpl_connect(
            'motion_notify_event', self.on_translate  # type: ignore[arg-type]
        )
        self.key_press_cid = self.current_canvas.mpl_connect(
            'key_press_event', self.on_key  # type: ignore[arg-type]
        )
        self.button_drag_cid = self.current_canvas.mpl_connect(
            'motion_notify_event', self.on_rotate  # type: ignore[arg-type]
        )
        self.axes_leave_cid: int = self.current_canvas.mpl_connect(
            'axes_leave_event', self.on_release  # type: ignore[arg-type]
        )
        self.current_canvas.setFocus()

    def translate_template(self, dx: float, dy: float) -> None:
        assert self.shape is not None
        self.shape.set_xy(self.shape.xy + np.array([dx, dy]))
        self.center = self.get_midpoint()
        self.redraw()

    def on_key_translate(self, event: KeyEvent) -> None:
        assert self.shape is not None
        dx0, dy0 = self.translation
        dx1, dy1 = 0.0, 0.0
        delta = KEY_TRANSLATE_DELTA
        if event.key == 'right':
            dx1 = delta
        elif event.key == 'left':
            dx1 = -delta
        elif event.key == 'up':
            dy1 = -delta
        elif event.key == 'down':
            dy1 = delta
        else:
            return

        self.translation = [dx0 + dx1, dy0 + dy1]
        self.shape.set_xy(self.shape.xy + np.array([dx1, dy1]))
        self.redraw()

    def on_press_translate(self, event: MouseEvent) -> None:
        assert self.shape is not None
        if event.inaxes != self.shape.axes or self.event_key == 'shift':
            return

        self.press = self.shape.xy, event.xdata, event.ydata  # type: ignore[assignment]

    def on_translate(self, event: MouseEvent) -> None:
        assert self.shape is not None
        if (
            self.press is None
            or event.inaxes != self.shape.axes
            or self.event_key == 'shift'
        ):
            return

        if event.xdata is None or event.ydata is None:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.center = self.get_midpoint()
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.redraw()

    def on_translate_release(self, event: MouseEvent) -> None:
        assert self.shape is not None
        if self.press is None or self.event_key == 'shift':
            return

        if event.xdata is None or event.ydata is None:
            return

        xy, xpress, ypress = self.press
        dx0, dy0 = self.translation
        dx1 = event.xdata - xpress
        dy1 = event.ydata - ypress
        self.translation = [dx0 + dx1, dy0 + dy1]
        self.shape.set_xy(xy + np.array([dx1, dy1]))
        self.press = None
        self.redraw()

    def on_press_rotate(self, event: MouseEvent) -> None:
        assert self.shape is not None
        if event.inaxes != self.shape.axes or self.event_key != 'shift':
            return

        # FIXME: Need to come back to this to understand why we
        # need to set the press value twice
        self.press = self.shape.xy, event.xdata, event.ydata  # type: ignore[assignment]
        self.center = self.get_midpoint()
        self.shape.set_transform(self.axis_image.axes.transData)
        self.press = self.shape.xy, event.xdata, event.ydata  # type: ignore[assignment]

    def rotate_template(self, points: np.ndarray, angle: float) -> None:
        assert self.shape is not None
        center = self.center
        canvas = self.current_canvas
        if canvas.mode == ViewType.polar:
            # We need to correct for the extent ratio and the aspect ratio
            # Make a copy to modify (we should *not* modify the original)
            points = np.array(points)
            # iviewer is PolarViewer here (mode == ViewType.polar)
            extent = canvas.iviewer.pv.extent  # type: ignore[union-attr]

            canvas_aspect = compute_aspect_ratio(canvas.axis)
            extent_aspect = (extent[2] - extent[3]) / (extent[1] - extent[0])

            aspect_ratio = extent_aspect * canvas_aspect
            points[:, 0] *= aspect_ratio
            center = [center[0] * aspect_ratio, center[1]]

        x = [np.cos(angle), np.sin(angle)]
        y = [-np.sin(angle), np.cos(angle)]
        verts = np.dot(points - center, np.array([x, y])) + center

        if canvas.mode == ViewType.polar:
            # Reverse the aspect ratio correction
            verts[:, 0] /= aspect_ratio

        self.shape.set_xy(verts)

    def on_rotate(self, event: MouseEvent) -> None:
        assert self.shape is not None
        if (
            self.press is None
            or event.inaxes != self.shape.axes
            or self.event_key != 'shift'
        ):
            return

        x, y = self.center
        xy, xpress, ypress = self.press
        angle = self.get_angle(event)
        self.rotate_template(xy, angle)
        self.redraw()

    def on_key_rotate(self, event: KeyEvent) -> None:
        assert self.shape is not None
        angle = self.key_rotation_angle
        # !!! only catch arrow keys
        if event.key == 'shift+left' or event.key == 'shift+up':
            angle *= -1.0
        elif event.key == 'shift+right' and event.key == 'shift+down':
            angle *= 1.0
        self.total_rotation += angle
        self.rotate_template(self.shape.xy, angle)
        self.redraw()

    def get_midpoint(self) -> list[float]:
        assert self.shape is not None
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return [(x1 + x0) / 2, (y1 + y0) / 2]

    def mouse_position(self, e: MouseEvent) -> tuple[float, float]:
        xmin, xmax, ymin, ymax = self.axis_image.get_extent()
        x, y = self.get_midpoint()
        xdata = e.xdata
        ydata = e.ydata
        if xdata is None:
            if e.x < x:
                xdata = 0
            else:
                xdata = xmax
        if ydata is None:
            if e.y < y:
                ydata = 0
            else:
                ydata = ymax
        return xdata, ydata

    def get_angle(self, e: MouseEvent) -> float:
        assert self.press is not None
        xy, xdata, ydata = self.press
        v0 = np.array([xdata, ydata]) - np.array(self.center)
        v1 = np.array(self.mouse_position(e)) - np.array(self.center)
        v0_u = v0 / np.linalg.norm(v0)
        v1_u = v1 / np.linalg.norm(v1)
        angle = np.arctan2(np.linalg.det([v0_u, v1_u]), np.dot(v0_u, v1_u))
        return angle

    def on_rotate_release(self, event: MouseEvent) -> None:
        if self.press is None or self.event_key != 'shift':
            return
        angle = self.get_angle(event)
        self.total_rotation += angle
        y, x = self.center
        xy, xpress, ypress = self.press
        self.press = None
        self.rotate_template(xy, angle)
        self.redraw()


def compute_aspect_ratio(axis: Axes) -> float:
    # Compute the aspect ratio of a matplotlib axis
    ll, ur = axis.get_position() * axis.figure.get_size_inches()  # type: ignore[union-attr]
    width, height = ur - ll
    return width / height
