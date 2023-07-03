from PySide2.QtCore import Signal, QTimer
from PySide2.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvas

from matplotlib.figure import Figure
from matplotlib.widgets import Cursor

import numpy as np

from hexrd.ui.constants import ViewType


class ZoomCanvas(FigureCanvas):

    point_picked = Signal(object)

    def __init__(self, main_canvas, draw_crosshairs=True):
        self.figure = Figure()
        super().__init__(self.figure)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.xdata = None
        self.ydata = None
        self.main_artists_visible = True
        self._display_sums_in_subplots = True

        self.i_row = None
        self.j_col = None
        self.roi = None

        self.main_canvas = main_canvas

        self.main_cursor = None
        self.cursor = None

        # Fire up the cursor for the main canvas
        self.recreate_main_cursor()

        # Create the rsimg we will use
        self.rsimg = self.create_rsimg()

        self.draw_crosshairs = draw_crosshairs

        self.axes = [None, None, None]
        self.axes_images = None
        self.frozen = False
        self.in_zoom_axis = False
        self.box_overlay_line = None

        # Set up the box overlay lines
        self.setup_box_overlay_lines()
        self.crosshairs = None
        self.vhlines = []
        self.disabled = False

        # user-specified ROI (from interactors)
        self.zoom_width = 15
        self.zoom_height = 60

        self.setup_connections()

    def setup_connections(self):
        self.mc_mne_id = self.main_canvas.mpl_connect(
            'motion_notify_event', self.main_canvas_mouse_moved)
        self.mc_de_id = self.main_canvas.mpl_connect(
            'draw_event', self.on_main_canvas_draw_event)
        self.mc_ae_id = self.main_canvas.mpl_connect('axes_enter_event',
                                                     self.on_axes_entered)
        self.mc_al_id = self.main_canvas.mpl_connect('axes_leave_event',
                                                     self.on_axes_exited)

        self.mne_id = self.mpl_connect('motion_notify_event',
                                       self.mouse_moved)
        self.bp_id = self.mpl_connect('button_press_event',
                                      self.button_pressed)

        self.main_canvas.transform_modified.connect(self.recreate_rsimg)
        self.main_canvas.cmap_modified.connect(self.render)
        self.main_canvas.norm_modified.connect(self.render)

    def setup_box_overlay_lines(self):
        self.remove_overlay_lines()
        self.box_overlay_line, = self.main_axis.plot([], [], 'm-',
                                                     animated=True)
        # We need to redraw the main canvas once so that the background
        # gets saved for blitting.
        self.main_canvas.draw_idle()

    def __del__(self):
        self.cleanup()

    def cleanup(self):
        self.disconnect()
        self.remove_all_cursors()
        self.remove_overlay_lines()
        self.main_canvas.draw_idle()

    def disconnect(self):
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

    def remove_all_cursors(self):
        self.remove_cursor()
        self.remove_main_cursor()

    def remove_cursor(self):
        if self.cursor:
            self.cursor.remove()
            self.cursor = None

    def remove_main_cursor(self):
        if self.main_cursor:
            self.main_cursor.remove()
            self.main_cursor = None

    def remove_overlay_lines(self):
        if self.box_overlay_line is not None:
            self.box_overlay_line.remove()
            self.box_overlay_line = None

    def clear_crosshairs(self):
        if self.crosshairs is not None:
            self.crosshairs.set_data([], [])

    def remove_crosshairs(self):
        if self.crosshairs is not None:
            self.crosshairs.remove()
            self.crosshairs = None

    def on_axes_entered(self, event):
        if self.canvas_is_raw and not self.frozen:
            # Set the axis to whatever axis we just entered
            self.main_axis = event.inaxes

    def on_axes_exited(self, event):
        pass

    def button_pressed(self, event):
        if self.disabled:
            return

        if event.button != 1:
            # Don't do anything if it isn't a left click
            return

        self.point_picked.emit(event)

    def mouse_moved(self, event):
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

    def update_vhlines(self, event):
        # These are vertical and horizontal lines on the integral axes
        if any(not x for x in [self.vhlines, self.axes]):
            return

        vline, hline = self.vhlines
        vline.set_xdata(event.xdata)
        hline.set_ydata(event.ydata)

    def main_canvas_mouse_moved(self, event):
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
        self.main_cursor.trigger_onmove(event)
        self.render()

    @property
    def canvas_is_raw(self):
        return self.image_mode == ViewType.raw

    @property
    def canvas_is_polar(self):
        return self.image_mode == ViewType.polar

    @property
    def pv(self):
        return self.main_canvas.iviewer.pv

    @property
    def image_mode(self):
        return self.main_canvas.mode

    @property
    def cursor_color(self):
        return self.main_cursor_color

    @property
    def main_cursor_color(self):
        return self.main_cursor.linev.get_color()

    @cursor_color.setter
    def cursor_color(self, color):
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
    def display_sums_in_subplots(self):
        return self._display_sums_in_subplots

    @display_sums_in_subplots.setter
    def display_sums_in_subplots(self, b):
        self._display_sums_in_subplots = b
        self.update_subplots()
        self.draw()

    @property
    def extent(self):
        if self.canvas_is_polar:
            return self.main_canvas.iviewer._extent
        else:
            return None

    def pixel_values_for_roi(self, roi):
        i_row = roi[:, 1]
        j_col = roi[:, 0]
        if self.canvas_is_polar:
            # get pixel values from PolarView class
            i_row = self.pv.eta_to_pixel(np.radians(i_row))
            j_col = self.pv.tth_to_pixel(np.radians(j_col))

        return i_row, j_col

    def plot_crosshairs(self, xlims, ylims):
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
            center - (xmag, 0)
        ]

        self.crosshairs.set_data(zip(*vals))

    def show_main_artists(self, show):
        self.box_overlay_line.set_visible(show)
        self.main_cursor.show(show)
        self.main_artists_visible = show

    def on_main_canvas_draw_event(self, event):
        if self.disabled:
            return

        invalid = (
            self.xdata is None or
            self.ydata is None or
            self.box_overlay_line is None
        )
        if invalid:
            return

        self.main_cursor.show(self.main_artists_visible)

        # Render...
        QTimer.singleShot(0, self.render)

    def update_subplots(self):
        rsimg = self.rsimg
        i_row, j_col = self.i_row, self.j_col
        roi = self.roi

        req = [rsimg, i_row, j_col, roi]
        if self.canvas_is_polar:
            req.append(self.pv)

        if any(x is None for x in req):
            return

        # In case the bounding box is out of bounds, we need to clip
        # the line and insert nans.
        a2_max = rsimg.shape[1]
        a2_x, valid_a2, a2_low, a2_high = _clip_range(j_col[0], j_col[1],
                                                      0, a2_max)
        a2_y = a2_x.copy()

        a3_max = rsimg.shape[0]
        a3_x, valid_a3, a3_low, a3_high = _clip_range(i_row[1], i_row[2],
                                                      0, a3_max)
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
                x, = self.vhlines[0].get_xdata()
                y, = self.vhlines[1].get_ydata()
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
                x_pixel = round(x)
                y_pixel = round(y)

            # Extract the points from the main image
            if y_pixel < rsimg.shape[0]:
                a2_y[valid_a2] = rsimg[y_pixel, a2_low:a2_high]

            if x_pixel < rsimg.shape[1]:
                a3_x[valid_a3] = rsimg[a3_low:a3_high, x_pixel]

        a2_data = (a2_x, a2_y)
        a3_data = (a3_x, a3_y)

        self.axes_images[1].set_data(a2_data)
        self.axes_images[2].set_data(a3_data)

        self.axes[1].relim()
        self.axes[1].autoscale_view()
        self.axes[2].relim()
        self.axes[2].autoscale_view()

    def create_zoom_image(self, a1):
        return a1.imshow(self.rsimg, extent=self.extent,
                         cmap=self.main_canvas.cmap,
                         norm=self.main_canvas.norm, picker=True,
                         interpolation='none')

    def render(self):
        if self.disabled:
            return

        self.clear_crosshairs()

        point = (self.xdata, self.ydata)
        if any(x is None for x in point):
            # Update and return
            self.main_cursor.draw_artists()
            self.main_axis.draw_artist(self.box_overlay_line)
            self.main_cursor.blit()
            return

        roi_diff = (np.tile([self.zoom_width, self.zoom_height], (4, 1)) *
                    0.5 * np.vstack([[-1, -1], [1, -1], [1, 1], [-1, 1]]))
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
            self.cursor = RemovableCursor(a1, useblit=True,
                                          color=self.cursor_color, linewidth=1)
            im2, = a2.plot([], [])
            im3, = a3.plot([], [])
            self.figure.suptitle(r"ROI zoom")
            a2.set_xlabel(self.x_label)
            a2.set_ylabel(r"intensity")
            a1.set_ylabel(self.y_label)
            a3.set_xlabel(r"intensity")
            self.crosshairs = a1.plot([], [], self.cursor_color,
                                      linestyle='-')[0]
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

            self.axes[0].set_xlim(*xlims)
            self.axes[0].set_ylim(*ylims)

            self.update_subplots()

        if self.draw_crosshairs:
            self.plot_crosshairs(xlims, ylims)

        xs = np.append(roi[:, 0], roi[0, 0])
        ys = np.append(roi[:, 1], roi[0, 1])
        self.box_overlay_line.set_data(xs, ys)

        # We are relying on the Cursor's background cache here in order
        # to do our blitting.
        # The main cursor should not be updated if we are frozen.
        if not self.frozen:
            self.main_cursor.draw_artists()

        self.main_axis.draw_artist(self.box_overlay_line)
        self.main_cursor.blit()

        # Redraw the zoom canvas
        self.draw_idle()

    @property
    def default_axis(self):
        if self.canvas_is_polar:
            return self.main_canvas.axis
        elif self.canvas_is_raw:
            return next(iter(self.main_canvas.raw_axes.values()))

    @property
    def x_label(self):
        if self.canvas_is_polar:
            return r"$2\theta$ [deg]"
        elif self.canvas_is_raw:
            return 'x'

    @property
    def y_label(self):
        if self.canvas_is_polar:
            return r"$\eta$ [deg]"
        elif self.canvas_is_raw:
            return 'y'

    @property
    def main_axis(self):
        return self.main_cursor.ax

    @main_axis.setter
    def main_axis(self, ax):
        if self.main_axis is ax:
            # Nothing to do
            return

        self.recreate_main_cursor(ax)
        self.setup_box_overlay_lines()

        # Recreate the zoom image
        self.recreate_rsimg()

    def recreate_main_cursor(self, axis=None):
        self.remove_main_cursor()

        if axis is None:
            axis = self.default_axis

        kwargs = {
            'ax': axis,
            'useblit': True,
            'color': 'red',
            'linewidth': 1,
        }
        self.main_cursor = MainCanvasCursor(**kwargs)

    def recreate_rsimg(self):
        self.rsimg = self.create_rsimg()
        self.recreate_zoom_image()

    def recreate_zoom_image(self):
        if not self.axes or not self.axes_images:
            return

        a1 = self.axes[0]
        self.axes_images[0] = self.create_zoom_image(a1)

        # Make sure this is autoscaled properly
        a1.axis('auto')

    def create_rsimg(self):
        if self.canvas_is_polar:
            return self.main_canvas.scaled_images[0]
        elif self.canvas_is_raw:
            name = self.main_axis.get_title()
            return self.main_canvas.scaled_image_dict[name]

    @property
    def disabled(self):
        return self._disabled

    @disabled.setter
    def disabled(self, b):
        self._disabled = b
        self.show_main_artists(not b)


class RemovableCursor(Cursor):
    # The Cursor doesn't appear to have cleanup methods, so we add them here.
    def remove(self):
        self.disconnect_events()

        if self.linev:
            self.linev.remove()
            self.linev = None

        if self.lineh:
            self.lineh.remove()
            self.lineh = None


class MainCanvasCursor(RemovableCursor):
    def _update(self):
        # Override this matplotlib function to stop automatic updates
        # Although this is an underscore function, it looks like it was
        # last touched in matplotlib 16 years ago, which means it's not
        # likely to change...
        pass

    def onmove(self, event):
        # Override this so that the normal onmove does not get called.
        # We do this so we can better control when this happens.
        pass

    def trigger_onmove(self, event):
        # Call the parent onmove
        super().onmove(event)

    def hide(self):
        self.show(False)

    def show(self, show=True):
        self.linev.set_visible(show)
        self.lineh.set_visible(show)

    def draw_artists(self):
        if self.background is not None:
            self.canvas.restore_region(self.background)
        self.ax.draw_artist(self.linev)
        self.ax.draw_artist(self.lineh)
        self.show()

    def blit(self):
        self.canvas.blit(self.ax.bbox)


def _clip_range(low, high, min_low, max_high):
    full_array = np.zeros(high - low)
    indices = np.arange(low, high)
    full_array[indices < min_low] = np.nan
    full_array[indices >= max_high] = np.nan

    valid = ~np.isnan(full_array)

    new_low = max(low, min_low)
    new_high = min(high, max_high)

    return full_array, valid, new_low, new_high
