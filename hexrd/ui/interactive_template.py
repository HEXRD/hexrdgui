from copy import copy
import numpy as np

from matplotlib.transforms import Affine2D, TransformedPatchPath
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path

from hexrd.ui import resource_loader
import hexrd.ui.resources.templates


class InteractiveTemplate:
    def __init__(self, img, parent=None, selection=None):
        self.selection = selection
        self.draw = bool(self.selection is None)
        self.parent = parent.image_canvases[0]
        self.ax = self.parent.axes_images[0]
        self.transform = self.ax.axes.transData
        self.img = img
        self.shape = None
        self.press = None

        if not self.draw:
            self.create_shape()
            self.connect()

    def create_shape(self):
        if self.draw:
            return
        else:
            l, r, t, b = self.ax.get_extent()
            centerx = (r-l)/2
            centery = (t-b)/2
            self.dx = (r-l)/2
            self.dy = (t-b)/2
            text = resource_loader.load_resource(
                hexrd.ui.resources.templates, self.selection + '.txt')
            verts = []
            for val in text.split('\n'):
                if not val.startswith('#') and val:
                    vert = val.split('\t')
                    verts.append([float(vert[0])/0.1+centerx, float(vert[1])/0.1+centery])
            self.shape = patches.Polygon(verts, fill=False, lw=1)
            self.parent.show()

    def get_shape(self):
        return self.shape
