import numpy as np

from matplotlib.transforms import Affine2D
import matplotlib.patches as patches
from matplotlib.path import Path

from hexrd.ui import resource_loader
import hexrd.ui.resources.templates


class InteractiveTemplate:
    def __init__(self, img, parent=None):
        self.parent = parent.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.transform = self.ax.axes.transData
        self.img = img
        self.shape = None
        self.press = None

    def create_shape(self, selection, pixel_size):
        if selection == 'Draw':
            return
        else:
            xsize, ysize = pixel_size
            l, r, t, b = self.ax.get_extent()
            midx = r-(r+l)/2
            midy = t-(t+b)/2
            text = resource_loader.load_resource(
                hexrd.ui.resources.templates, selection + '.txt')
            verts = []
            for val in text.split('\n'):
                if not val.startswith('#') and val:
                    vert = val.split('\t')
                    x = float(vert[0])/xsize+midx
                    y = float(vert[1])/ysize+midy
                    verts.append([x, y])
            self.shape = patches.Polygon(verts, fill=False, lw=1)
            self.connect()
            self.parent.show()

    def get_shape(self):
        return self.shape

    def get_mask(self):
        return self.mask

    def create_mask(self):
        h, w = self.img.shape
        x, y = np.meshgrid(np.arange(w), np.arange(h))
        coords = np.vstack((x.flatten(), y.flatten())).T
        transformed_paths = self.get_paths()
        self.mask = np.zeros(self.img.shape)
        for path in transformed_paths:
            points = path.contains_points(coords)
            grid = points.reshape(h, w)
            self.mask = (self.mask != grid)

    def get_paths(self):
        all_paths = []
        verts = self.shape.get_patch_transform().transform(
            self.shape.get_path().vertices)
        if hasattr(self, 'affine2d'):
            verts = self.affine2d.transform(verts)
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

    def connect(self):
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

    def disconnect(self):
        self.parent.mpl_disconnect(self.button_press_cid)
        self.parent.mpl_disconnect(self.button_release_cid)
        self.parent.mpl_disconnect(self.motion_cid)
