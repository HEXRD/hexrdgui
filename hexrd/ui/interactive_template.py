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
        self.img = img
        self.shape = None

    def create_shape(self, file_name):
        text = resource_loader.load_resource(
            hexrd.ui.resources.templates, file_name + '.txt')
        verts = []
        for val in text.split('\n'):
            if not val.startswith('#') and val:
                vert = val.split('\t')
                verts.append([float(vert[0])/0.1, float(vert[1])/0.1])
        self.shape = patches.Polygon(verts, fill=False, lw=1)
        self.raw_axes.add_patch(self.shape)
        self.parent.draw()

    def get_shape(self):
        return self.shape

    def clear(self):
        self.raw_axes.patches.remove(self.shape)
        self.parent.draw()
