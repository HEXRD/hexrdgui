import numpy as np

from matplotlib.transforms import Affine2D
from matplotlib import patches

from hexrd.ui import resource_loader
import hexrd.ui.resources.templates


class InteractiveTemplate:
    def __init__(self, img, parent=None):
        # TODO: Handle more than one image being loaded
        self.parent = parent.image_tab_widget.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.raw_axes = self.parent.raw_axes[0]
        self.transform = self.ax.axes.transData
        self.img = img
        self.shape = None
        self.press = None

    def create_shape(self, file_name):
        text = resource_loader.load_resource(
            hexrd.ui.resources.templates, file_name + '.txt')
        verts = []
        for val in text.split('\n'):
            if not val.startswith('#') and val:
                vert = val.split('\t')
                verts.append([float(vert[0])/0.1, float(vert[1])/0.1])
        self.shape = patches.Polygon(verts, fill=False, lw=1)
        self.connect_translate()
        self.raw_axes.add_patch(self.shape)
        self.parent.draw()

    def get_shape(self):
        return self.shape

    def clear(self):
        self.raw_axes.patches.remove(self.shape)
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
        self.parent.draw()

    def on_release(self, event):
        if self.press is None:
            return

        xy, xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.shape.set_xy(xy + np.array([dx, dy]))
        self.press = None
        self.center = self.get_midpoint()
        self.parent.draw()

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
        self.parent.draw()

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
        # self.shape.set_transform(self.transform)
        self.parent.draw()

    def disconnect_rotate(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_drag_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
