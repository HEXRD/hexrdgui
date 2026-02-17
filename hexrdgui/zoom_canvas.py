from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

from matplotlib.axes import Axes
from matplotlib.backend_bases import (
    DrawEvent,
    LocationEvent,
    MouseEvent,
)
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.widgets import Cursor

import numpy as np

from hexrdgui.constants import ViewType
from hexrdgui.utils.matplotlib import remove_artist

if TYPE_CHECKING:
    from hexrdgui.image_canvas import ImageCanvas


class ZoomCanvas(FigureCanvas):

    point_picked = Signal(object)

    def __init__(
        self,
        main_canvas: ImageCanvas,
        draw_crosshairs: bool = True,
        display_sums_in_subplots: bool = False,
    ) -> None:
        self.figure = Figure()
        super().__init__(self.figure)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.xdata: float | None = None
        self.ydata: float | None = None
        self.main_artists_visible = True
        self._display_sums_in_subplots = display_sums_in_subplots

        self.i_row: np.ndarray | None = None
        self.j_col: np.ndarray | None = None
        self.roi: np.ndarray | None = None

        self.main_canvas = main_canvas

        self.main_cursor: MainCanvasCursor | None = None
        self.cursor: RemovableCursor | None = None

        # Fire up the cursor for the main canvas
        self.recreate_main_cursor()

        # Create the rsimg we will use
        self.rsimg = self.create_rsimg()

        self.draw_crosshairs = draw_crosshairs

        self.axes: list[Axes | None] = [None, None, None]
        self.axes_images: list[Any] | None = None
        self.frozen = False
        self.in_zoom_axis = False
        self.box_overlay_line: Line2D | None = None

        # Set up the box overlay lines
        self.setup_box_overlay_lines()
        self.crosshairs: Line2D | None = None
        self.vhlines: list[Line2D] = []
        self.disabled = False

        self.was_disconnected = False

        # user-specified ROI (from interactors)
        self.zoom_width = 15
        self.zoom_height = 150

        # Keep track of whether we should skip a render (due to point picking)
        self.skip_next_render = False

        self.setup_connections()

    def setup_connections(self) -> None:
        self.mc_mne_id = self.main_canvas.mpl_connect(
            'motion_notify_event', self.main_canvas_mouse_moved  # type: ignore[arg-type]
        )
        self.mc_de_id = self.main_canvas.mpl_connect(
            'draw_event', self.on_main_canvas_draw_event  # type: ignore[arg-type]
        )
        self.mc_ae_id = self.main_canvas.mpl_connect(
            'axes_enter_event', self.on_axes_entered  # type: ignore[arg-type]
        )
        self.mc_al_id = self.main_canvas.mpl_connect(
            'axes_leave_event', self.on_axes_exited  # type: ignore[arg-type]
        )

        self.mne_id = self.mpl_connect('motion_notify_event', self.mouse_moved)  # type: ignore[arg-type]
        self.bp_id = self.mpl_connect('button_press_event', self.button_pressed)  # type: ignore[arg-type]

        self.main_canvas.transform_modified.connect(self.recreate_rsimg)
        self.main_canvas.cmap_modified.connect(self.render)
        self.main_canvas.norm_modified.connect(self.render)

    def setup_box_overlay_lines(self) -> None:
        self.remove_overlay_lines()
        (self.box_overlay_line,) = self.main_axis.plot([], [], 'm-', animated=True)
        # We need to redraw the main canvas once so that the background
        # gets saved for blitting.
        self.main_canvas.draw_idle()

    def __del__(self) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self.was_disconnected:
            # It was already cleaned up
            return

        self.disconnect()
        self.remove_all_cursors()
        self.remove_overlay_lines()
        self.main_canvas.draw_idle()
        self.deleteLater()
        self.was_disconnected = True

    def disconnect(self) -> None:
        mc_disconnect = [
            'mc_mne_id',
            'mc_de_id',
            'mc_ae_id',
            'mc_al_id',
        ]
        for name in mc_disconnect:
            var = getattr(self, name)
            if var is not None:
                self.main_canvas.mpl_disconnect(var)
                setattr(self, name, None)

        self_disconnect = [
            'mne_id',
            'bp_id',
        ]
        for name in self_disconnect:
            var = getattr(self, name)
            if var is not None:
                self.mpl_disconnect(var)
                setattr(self, name, None)

    def remove_all_cursors(self) -> None:
        self.remove_cursor()
        self.remove_main_cursor()

    def remove_cursor(self) -> None:
        if self.cursor:
            remove_artist(self.cursor)  # type: ignore[arg-type]
            self.cursor = None

    def remove_main_cursor(self) -> None:
        if self.main_cursor:
            remove_artist(self.main_cursor)  # type: ignore[arg-type]
            self.main_cursor = None

    def remove_overlay_lines(self) -> None:
        if self.box_overlay_line is not None:
            remove_artist(self.box_overlay_line)
            self.box_overlay_line = None

    def clear_crosshairs(self) -> None:
        if self.crosshairs is not None:
            self.crosshairs.set_data([], [])

    def remove_crosshairs(self) -> None:
        if self.crosshairs is not None:
            remove_artist(self.crosshairs)
            self.crosshairs = None

    def on_axes_entered(self, event: LocationEvent) -> None:
        if self.canvas_is_raw and not self.frozen:
            # Set the axis to whatever axis we just entered
            assert event.inaxes is not None
            self.main_axis = event.inaxes

    def on_axes_exited(self, event: LocationEvent) -> None:
        pass

    def button_pressed(self, event: MouseEvent) -> None:
        if self.disabled:
            return

        if event.button != 1:
            # Don't do anything if it isn't a left click
            return

        # The zoom canvas doesn't need to be rerendered after point picking,
        # but it will be asked to rerender anyways (due to the main canvas
        # being redrawn). Skip this zoom canvas rerender.
        self.skip_next_render = True
        self.point_picked.emit(event)

    def mouse_moved(self, event: MouseEvent) -> None:
        if self.disabled:
            return

        # Clear the crosshairs when the mouse is moving over the canvas
        self.clear_crosshairs()
        self.update_vhlines(event)

        self.in_zoom_axis = event.inaxes == self.axes[0]

        if not self.display_sums_in_subplots:
            self.update_subplots()

        # Can't use draw_idle() since the Cursor has useblit=True
        self.draw()

    def update_vhlines(self, event: MouseEvent) -> None:
        # These are vertical and horizontal lines on the integral axes
        if any(not x for x in [self.vhlines, self.axes]):
            return

        vline, hline = self.vhlines
        vline.set_xdata([event.xdata])  # type: ignore[arg-type]
        hline.set_ydata([event.ydata])  # type: ignore[arg-type]

    def main_canvas_mouse_moved(self, event: MouseEvent) -> None:
        if self.disabled:
            return

        if event.inaxes is None:
            # Do nothing...
            return

        if self.main_axis is event.inaxes:
            self.in_zoom_axis = False

        if self.canvas_is_polar and not event.inaxes.get_images():
            # Image is over intensity plot. Do nothing...
            return

        if self.frozen:
            # Do not render if frozen
            return

        self.xdata = event.xdata
        self.ydata = event.ydata

        # Trigger the mouse move event for the main cursor, so it will update.
        assert self.main_cursor is not None
        self.main_cursor.trigger_onmove(event)
        self.render()

    @property
    def canvas_is_raw(self) -> bool:
        return self.image_mode == ViewType.raw

    @property
    def canvas_is_polar(self) -> bool:
        return self.image_mode == ViewType.polar

    @property
    def pv(self) -> Any:
        # pv exists on PolarViewer and StereoViewer
        return self.main_canvas.iviewer.pv  # type: ignore[union-attr]

    @property
    def image_mode(self) -> str | None:
        return self.main_canvas.mode

    @property
    def cursor_color(self) -> str:
        return self.main_cursor_color

    @property
    def main_cursor_color(self) -> Any:
        assert self.main_cursor is not None
        assert self.main_cursor.linev is not None
        return self.main_cursor.linev.get_color()

    @cursor_color.setter  # type: ignore[no-redef, attr-defined]
    def cursor_color(self, color: str) -> None:
        assert self.main_cursor is not None
        to_set = [
            self.main_cursor.linev,
            self.main_cursor.lineh,
            self.crosshairs,
            *self.vhlines,
        ]
        if self.cursor:
            to_set += [self.cursor.linev, self.cursor.lineh]

        for artist in to_set:
            if artist is None:
                continue

            artist.set_color(color)

    @property
    def display_sums_in_subplots(self) -> bool:
        return self._display_sums_in_subplots

    @display_sums_in_subplots.setter
    def display_sums_in_subplots(self, b: bool) -> None:
        self._display_sums_in_subplots = b
        self.update_subplots()
        self.draw()

    @property
    def extent(self) -> list[float] | np.ndarray | None:
        if self.canvas_is_polar:
            # _extent exists on PolarViewer
            return self.main_canvas.iviewer._extent  # type: ignore[union-attr]
        else:
            return None

    def pixel_values_for_roi(self, roi: np.ndarray) -> tuple:
        i_row = roi[:, 1]
        j_col = roi[:, 0]
        if self.canvas_is_polar:
            # get pixel values from PolarView class
            i_row = self.pv.eta_to_pixel(np.radians(i_row))
            j_col = self.pv.tth_to_pixel(np.radians(j_col))

        return i_row, j_col

    def plot_crosshairs(self, xlims: np.ndarray, ylims: np.ndarray) -> None:
        x_scale = 0.05
        y_scale = 0.05

        center = np.array([np.mean(xlims), np.mean(ylims)])

        xmag = abs(xlims[1] - xlims[0]) * x_scale
        ymag = abs(ylims[1] - ylims[0]) * y_scale

        vals = [
            center + (0, ymag),
            center - (0, ymag),
            (np.nan, np.nan),
            center + (xmag, 0),
            center - (xmag, 0),
        ]

        assert self.crosshairs is not None
        self.crosshairs.set_data(list(zip(*vals)))

    def show_main_artists(self, show: bool) -> None:
        assert self.box_overlay_line is not None
        assert self.main_cursor is not None
        self.box_overlay_line.set_visible(show)
        self.main_cursor.show(show)
        self.main_artists_visible = show

    def on_main_canvas_draw_event(self, event: DrawEvent) -> None:
        if self.disabled:
            return

        invalid = (
            self.xdata is None or self.ydata is None or self.box_overlay_line is None
        )
        if invalid:
            return

        assert self.main_cursor is not None
        self.main_cursor.show(self.main_artists_visible)

        # Update the zoom window (in case it is needed)...
        QTimer.singleShot(0, self.render)

    def update_subplots(self) -> None:
        rsimg = self.rsimg
        i_row, j_col = self.i_row, self.j_col
        roi = self.roi

        req = [rsimg, i_row, j_col, roi]
        if self.canvas_is_polar:
            req.append(self.pv)

        if any(x is None for x in req):
            return

        assert i_row is not None
        assert j_col is not None
        assert roi is not None
        assert self.axes_images is not None

        # In case the bounding box is out of bounds, we need to clip
        # the line and insert nans.
        a2_max = rsimg.shape[1]
        a2_x, valid_a2, a2_low, a2_high = _clip_range(j_col[0], j_col[1], 0, a2_max)
        a2_y = a2_x.copy()

        a3_max = rsimg.shape[0]
        a3_x, valid_a3, a3_low, a3_high = _clip_range(i_row[1], i_row[2], 0, a3_max)
        a3_y = a3_x.copy()

        if self.canvas_is_polar:
            angular_grid = self.pv.angular_grid
            a2_x[valid_a2] = np.degrees(angular_grid[1][0, a2_low:a2_high])
            a3_y[valid_a3] = np.degrees(angular_grid[0][a3_low:a3_high, 0])
        else:
            a2_x[valid_a2] = np.arange(a2_low, a2_high)
            a3_y[valid_a3] = np.arange(a3_low, a3_high)

        if self.display_sums_in_subplots:
            roi = rsimg[a3_low:a3_high, a2_low:a2_high]
            a2_y[valid_a2] = np.nansum(roi, axis=0)
            a3_x[valid_a3] = np.nansum(roi, axis=1)
        else:
            if self.in_zoom_axis and self.vhlines:
                (x,) = self.vhlines[0].get_xdata()  # type: ignore[misc]
                (y,) = self.vhlines[1].get_ydata()  # type: ignore[misc]
            else:
                # Use the center of the plot
                xlims = roi[0:2, 0]
                ylims = roi[2:0:-1, 1]
                x, y = np.mean(xlims), np.mean(ylims)

            if self.canvas_is_polar:
                # Convert to pixels
                x_pixel = round(self.pv.tth_to_pixel(np.radians(x)).item())
                y_pixel = round(self.pv.eta_to_pixel(np.radians(y)).item())
            else:
                x_pixel = round(x)  # type: ignore[arg-type]
                y_pixel = round(y)  # type: ignore[arg-type]

            # Extract the points from the main image
            if y_pixel < rsimg.shape[0]:
                a2_y[valid_a2] = rsimg[y_pixel, a2_low:a2_high]

            if x_pixel < rsimg.shape[1]:
                a3_x[valid_a3] = rsimg[a3_low:a3_high, x_pixel]

        a2_data = (a2_x, a2_y)
        a3_data = (a3_x, a3_y)

        self.axes_images[1].set_data(a2_data)
        self.axes_images[2].set_data(a3_data)

        assert self.axes[1] is not None
        assert self.axes[2] is not None
        self.axes[1].relim()
        self.axes[1].autoscale_view()
        self.axes[2].relim()
        self.axes[2].autoscale_view()

    def create_zoom_image(self, a1: Axes) -> Any:
        return a1.imshow(
            self.rsimg,
            extent=self.extent,  # type: ignore[arg-type]
            cmap=self.main_canvas.cmap,
            norm=self.main_canvas.norm,
            picker=True,
            interpolation='none',
        )

    def render(self) -> None:
        if self.disabled:
            return

        if self.skip_next_render:
            self.skip_next_render = False
            return

        self.clear_crosshairs()

        if self.xdata is None or self.ydata is None:
            # Update and return
            assert self.main_cursor is not None
            self.main_cursor.draw_artists()
            if self.box_overlay_line is not None:
                self.main_axis.draw_artist(self.box_overlay_line)
            self.main_cursor.blit()
            return

        point = (self.xdata, self.ydata)
        roi_diff = (
            np.tile([self.zoom_width, self.zoom_height], (4, 1))
            * 0.5
            * np.vstack([[-1, -1], [1, -1], [1, 1], [-1, 1]])
        )
        roi = np.tile(point, (4, 1)) + roi_diff

        self.roi = roi
        i_row, j_col = self.pixel_values_for_roi(roi)

        # Convert to integers
        i_row = np.round(i_row).astype(int)
        j_col = np.round(j_col).astype(int)

        self.i_row, self.j_col = i_row, j_col

        xlims = roi[0:2, 0]
        ylims = roi[2:0:-1, 1]

        if self.axes_images is None:
            grid = self.figure.add_gridspec(5, 5)
            a1 = self.figure.add_subplot(grid[:4, :4])
            a2 = self.figure.add_subplot(grid[4, :4], sharex=a1)
            a3 = self.figure.add_subplot(grid[:4, 4], sharey=a1)
            a1.set_xlim(*xlims)
            a1.set_ylim(*ylims)
            im1 = self.create_zoom_image(a1)

            a1.axis('auto')
            a1.label_outer()
            a3.label_outer()
            a3.tick_params(labelbottom=True)  # Label bottom anyways for a3
            self.cursor = RemovableCursor(
                a1, useblit=True, color=self.cursor_color, linewidth=1
            )
            (im2,) = a2.plot([], [])
            (im3,) = a3.plot([], [])
            self.figure.suptitle(r"ROI zoom")
            a2.set_xlabel(self.x_label or "")
            a2.set_ylabel(r"intensity")
            a1.set_ylabel(self.y_label or "")
            a3.set_xlabel(r"intensity")
            self.crosshairs = a1.plot([], [], self.cursor_color, linestyle='-')[0]
            self.axes = [a1, a2, a3]
            self.axes_images = [im1, im2, im3]
            self.grid = grid

            # These are vertical and horizontal lines on the integral axes
            vline = a2.axvline(0, color=self.cursor_color, linewidth=1)
            hline = a3.axhline(0, color=self.cursor_color, linewidth=1)
            self.vhlines = [vline, hline]

            self.update_subplots()
        else:
            # Make sure we update the color map and norm each time
            self.axes_images[0].set_cmap(self.main_canvas.cmap)
            self.axes_images[0].set_norm(self.main_canvas.norm)

            assert self.axes[0] is not None
            self.axes[0].set_xlim(*xlims)
            self.axes[0].set_ylim(*ylims)

            self.update_subplots()

        if self.draw_crosshairs:
            self.plot_crosshairs(xlims, ylims)

        xs = np.append(roi[:, 0], roi[0, 0])
        ys = np.append(roi[:, 1], roi[0, 1])
        assert self.box_overlay_line is not None
        self.box_overlay_line.set_data(xs, ys)

        # We are relying on the Cursor's background cache here in order
        # to do our blitting.
        # The main cursor should not be updated if we are frozen.
        assert self.main_cursor is not None
        if not self.frozen:
            self.main_cursor.draw_artists()

        self.main_axis.draw_artist(self.box_overlay_line)
        self.main_cursor.blit()

        # Redraw the zoom canvas
        self.draw_idle()

    @property
    def default_axis(self) -> Axes | None:
        if self.canvas_is_polar:
            return self.main_canvas.axis
        elif self.canvas_is_raw:
            return next(iter(self.main_canvas.raw_axes.values()))
        return None

    @property
    def x_label(self) -> str | None:
        if self.canvas_is_polar:
            return r"$2\theta$ [deg]"
        elif self.canvas_is_raw:
            return 'x'
        return None

    @property
    def y_label(self) -> str | None:
        if self.canvas_is_polar:
            return r"$\eta$ [deg]"
        elif self.canvas_is_raw:
            return 'y'
        return None

    @property
    def main_axis(self) -> Axes:
        assert self.main_cursor is not None
        return self.main_cursor.ax

    @main_axis.setter
    def main_axis(self, ax: Axes) -> None:
        if self.main_axis is ax:
            # Nothing to do
            return

        self.recreate_main_cursor(ax)
        self.setup_box_overlay_lines()

        # Recreate the zoom image
        self.recreate_rsimg()

    def recreate_main_cursor(self, axis: Axes | None = None) -> None:
        self.remove_main_cursor()

        if axis is None:
            axis = self.default_axis

        kwargs = {
            'ax': axis,
            'useblit': True,
            'color': 'red',
            'linewidth': 1,
        }
        self.main_cursor = MainCanvasCursor(**kwargs)  # type: ignore[arg-type]

    def recreate_rsimg(self) -> None:
        self.rsimg = self.create_rsimg()
        self.recreate_zoom_image()

    def recreate_zoom_image(self) -> None:
        if not self.axes or not self.axes_images:
            return

        a1 = self.axes[0]
        assert a1 is not None
        self.axes_images[0] = self.create_zoom_image(a1)

        # Make sure this is autoscaled properly
        a1.axis('auto')

    def create_rsimg(self) -> Any:
        if self.canvas_is_polar:
            return self.main_canvas.scaled_images[0]
        elif self.canvas_is_raw:
            name = self.main_axis.get_title()
            return self.main_canvas.raw_view_images_dict[name]

    @property
    def disabled(self) -> bool:
        return self._disabled

    @disabled.setter
    def disabled(self, b: bool) -> None:
        self._disabled = b
        self.show_main_artists(not b)


class RemovableCursor(Cursor):
    linev: Line2D | None  # type: ignore[assignment]
    lineh: Line2D | None  # type: ignore[assignment]

    # The Cursor doesn't appear to have cleanup methods, so we add them here.
    def remove(self) -> None:
        self.disconnect_events()

        if self.linev:
            remove_artist(self.linev)
            self.linev = None

        if self.lineh:
            remove_artist(self.lineh)
            self.lineh = None


class MainCanvasCursor(RemovableCursor):
    def _update(self) -> None:
        # Override this matplotlib function to stop automatic updates
        # Although this is an underscore function, it looks like it was
        # last touched in matplotlib 16 years ago, which means it's not
        # likely to change...
        pass

    def onmove(self, event: MouseEvent) -> None:  # type: ignore[override]
        # Override this so that the normal onmove does not get called.
        # We do this so we can better control when this happens.
        pass

    def trigger_onmove(self, event: MouseEvent) -> None:
        # Call the parent onmove
        super().onmove(event)

    def hide(self) -> None:
        self.show(False)

    def show(self, show: bool = True) -> None:
        assert self.linev is not None
        assert self.lineh is not None
        self.linev.set_visible(show)
        self.lineh.set_visible(show)

    def draw_artists(self) -> None:
        if self.background is not None and self.canvas is not None:
            self.canvas.restore_region(self.background)  # type: ignore[attr-defined]
        if self.linev is not None:
            self.ax.draw_artist(self.linev)
        if self.lineh is not None:
            self.ax.draw_artist(self.lineh)
        self.show()

    def blit(self) -> None:
        if self.canvas is not None:
            self.canvas.blit(self.ax.bbox)


def _clip_range(low: int, high: int, min_low: int, max_high: int) -> tuple:
    full_array = np.zeros(high - low)
    indices = np.arange(low, high)
    full_array[indices < min_low] = np.nan
    full_array[indices >= max_high] = np.nan

    valid = ~np.isnan(full_array)

    new_low = max(low, min_low)
    new_high = min(high, max_high)

    return full_array, valid, new_low, new_high
