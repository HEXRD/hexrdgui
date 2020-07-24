import numpy as np

from matplotlib.transforms import Affine2D
from matplotlib import patches
from matplotlib.path import Path

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui import resource_loader


class InteractiveTemplate:
    def __init__(self, img, parent=None):
        self.parent = parent.image_tab_widget.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.raw_axes = self.parent.raw_axes[0]
        self.transform = self.ax.axes.transData
        self.img = img
        self.shape = None
        self.press = None

    def create_shape(self, module, file_name):
        with resource_loader.resource_path(module, file_name) as f:
            verts = np.loadtxt(f)
        pixel_size = HexrdConfig().detector_pixel_size('detector')
        verts = [vert/pixel_size for vert in verts]
        self.shape = patches.Polygon(verts, fill=False, lw=1)
        min_vals = np.nanmin(self.shape.xy, axis=0)
        max_vals = np.nanmax(self.shape.xy, axis=0)
        l, r, b, t = self.ax.get_extent()
        translate = [0, 0]
        if not self.raw_axes.contains_point(min_vals):
            translate = [l, t] - np.nanmin(self.shape.xy, axis=0)
        elif not self.raw_axes.contains_point(max_vals):
            translate = [r, b] - np.nanmax(self.shape.xy, axis=0)
        self.shape.set_xy(self.shape.xy + translate)
        self.connect_translate()
        self.raw_axes.add_patch(self.shape)
        self.redraw()

    def get_shape(self):
        return self.shape

    def get_mask(self):
        self.mask()
        return self.img

    def clear(self):
        self.raw_axes.patches.remove(self.shape)
        self.redraw()

    def mask(self):
        h, w = self.img.shape
        x, y = np.meshgrid(np.arange(w), np.arange(h))
        coords = np.vstack((x.flatten(), y.flatten())).T
        transformed_paths = self.get_paths()
        self.mask = np.zeros(self.img.shape)
        for path in transformed_paths:
            points = path.contains_points(coords)
            grid = points.reshape(h, w)
            self.mask = (self.mask != grid)
        self.original = self.ax.get_array()
        self.img[~self.mask] = 0

    def get_paths(self):
        all_paths = []
        verts = self.shape.get_patch_transform().transform(
            self.shape.get_path().vertices)
        if hasattr(self, 'rotate'):
            self.rotate.transform(verts)
        points = []
        codes = []
        for coords in verts:
            if np.isnan(coords).any():
                codes[0] = Path.MOVETO
                all_paths.append(Path(points, codes))
                codes = []
                points = []
            else:
                codes.append(Path.LINETO)
                points.append(coords)
        codes[0] = Path.MOVETO
        all_paths.append(Path(points, codes))

        return all_paths

    def crop(self):
        l, r, b, t = self.ax.get_extent()
        x0, y0 = np.nanmin(self.shape.xy, axis=0)
        x1, y1 = np.nanmax(self.shape.xy, axis=0)
        return np.floor(y0), np.ceil(y1), np.floor(x0), np.ceil(x1)

    def redraw(self):
        self.parent.draw()

    def connect_translate(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press_translate)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_release)
        self.motion_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_translate)

    def on_press_translate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.shape.set_transform(self.transform)
        self.press = self.shape.xy, event.xdata, event.ydata

    def on_translate(self, event):
        if self.press is None or event.inaxes != self.shape.axes:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.redraw()

    def on_release(self, event):
        if self.press is None:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.press = None
        self.center = self.get_midpoint()
        self.redraw()

    def disconnect_translate(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
        self.parent.mpl_disconnect(self.motion_cid)

    def connect_rotate(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press_rotate)
        self.button_drag_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_rotate)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_rotate_release)

    def on_press_rotate(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.shape.set_transform(self.ax.axes.transData)
        self.press = self.shape.xy, event.xdata, event.ydata

    def on_rotate(self, event):
        if self.press is None:
            return

        x, y = self.center
        angle = self.get_angle(event)
        trans = Affine2D().rotate_around(x, y, angle)
        self.shape.set_transform(trans + self.ax.axes.transData)
        self.redraw()

    def get_midpoint(self):
        length = len(self.shape.get_xy())
        sum_x = np.nansum(self.shape.get_xy()[:, 0])
        sum_y = np.nansum(self.shape.get_xy()[:, 1])
        return sum_x/length, sum_y/length

    def mouse_position(self, e):
        xmin, xmax, ymin, ymax = self.ax.get_extent()
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

    def get_angle(self, e):
        xy, xdata, ydata = self.press
        v0 = np.array([xdata, ydata]) - np.array(self.center)
        v1 = np.array(self.mouse_position(e)) - np.array(self.center)
        v0_u = v0/np.linalg.norm(v0)
        v1_u = v1/np.linalg.norm(v1)
        angle = np.arctan2(np.linalg.det([v0_u, v1_u]), np.dot(v0_u, v1_u))
        return angle

    def on_rotate_release(self, event):
        if self.press is None:
            return

        angle = self.get_angle(event)
        y, x = self.center
        self.press = None
        self.rotate = Affine2D().rotate_around(x, y, angle)
        self.transform = self.rotate + self.ax.axes.transData
        self.redraw()

    def disconnect_rotate(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_drag_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
