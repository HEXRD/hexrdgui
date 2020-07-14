import numpy as np

from matplotlib.transforms import Affine2D
from matplotlib import lines, patches
from matplotlib.path import Path

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
        self.connect_template()
        self.raw_axes.add_patch(self.shape)
        self.parent.draw()

    def get_shape(self):
        return self.shape

    def clear(self):
        self.raw_axes.patches.remove(self.shape)
        self.parent.draw()

    def connect_template(self):
        self.button_press_cid = self.parent.mpl_connect(
            'button_press_event', self.on_press)
        self.button_release_cid = self.parent.mpl_connect(
            'button_release_event', self.on_release)
        self.motion_cid = self.parent.mpl_connect(
            'motion_notify_event', self.on_motion)

    def on_press(self, event):
        if event.inaxes != self.shape.axes:
            return

        contains, info = self.shape.contains(event)
        if not contains:
            return
        self.shape.set_transform(self.transform)
        self.press = event.xdata, event.ydata

    def on_motion(self, event):
        if self.press is None or event.inaxes != self.shape.axes:
            return

        self.translate_shape(event)

    def translate_shape(self, event):
        xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.shape.set_transform(Affine2D().translate(dx, dy) + self.transform)
        self.parent.draw()

    def on_release(self, event):
        if self.press is None:
            return

        xpress, ypress = self.press
        dx = event.xdata - xpress
        dy = event.ydata - ypress
        self.press = None
        self.affine2d = Affine2D().translate(dx, dy)
        self.transform = self.affine2d + self.transform
        self.shape.set_transform(self.transform)
        self.parent.draw()

    def disconnect_template(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
        self.parent.mpl_disconnect(self.motion_cid)
