import math

import numpy as np

from matplotlib.backends.backend_qt5agg import (
    FigureCanvas, NavigationToolbar2QT
)
from matplotlib.backend_bases import MouseButton
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from hexrd.ui.calibration.cartesian_plot import cartesian_image
from hexrd.ui.calibration.polar_plot import polar_image
from hexrd.ui.hexrd_config import HexrdConfig
import hexrd.ui.constants

class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_names=None):
        self.figure = Figure()
        super(ImageCanvas, self).__init__(self.figure)

        self.navigation_toolbar = NavigationToolbar2QT(self, None)

        # We will be in zoom mode by default
        self.navigation_toolbar.zoom()

        self.axes_images = []
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None

        self.press_conn_id = self.mpl_connect('button_press_event',
                                              self.on_button_pressed)

        if image_names is not None:
            self.load_images(image_names)

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def load_images(self, image_names):
        self.figure.clear()
        self.axes_images.clear()

        cols = 1
        if len(image_names) > 1:
            cols = 2

        rows = math.ceil(len(image_names) / cols)

        for i, name in enumerate(image_names):
            img = HexrdConfig().image(name)

            axis = self.figure.add_subplot(rows, cols, i + 1)
            axis.set_title(name)
            self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                                norm=self.norm))

        self.figure.tight_layout()
        self.draw()

    def show_calibration(self):
        self.figure.clear()
        self.axes_images.clear()

        img, ring_data = cartesian_image()

        axis = self.figure.add_subplot(111)
        for pr in ring_data:
            axis.plot(pr[:, 1], pr[:, 0], 'c.', ms=2)

        self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                            norm=self.norm))

        self.figure.tight_layout()
        self.draw()

    def show_polar_calibration(self):
        self.figure.clear()
        self.axes_images.clear()

        img, extent, ring_data, rbnd_data = polar_image()

        axis = self.figure.add_subplot(111)

        self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                            norm=self.norm, picker=True,
                                            interpolation='none'))

        # We must adjust the extent of the image
        self.axes_images[0].set_extent(extent)
        axis.relim()
        axis.autoscale_view()
        axis.axis('auto')

        colorspec = 'c-.'
        for pr in ring_data:
            axis.plot(pr[:, 1], pr[:, 0], colorspec, ms=2)
        for pr in rbnd_data:
            axis.plot(pr[:, 1], pr[:, 0], 'm:', ms=1)

        self.figure.tight_layout()
        self.draw()

    def set_cmap(self, cmap):
        self.cmap = cmap
        for axes_image in self.axes_images:
            axes_image.set_cmap(cmap)
        self.draw()

    def set_norm(self, norm):
        self.norm = norm
        for axes_image in self.axes_images:
            axes_image.set_norm(norm)
        self.draw()

    def get_min_max(self):
        minimum = min([x.get_array().min() for x in self.axes_images])
        maximum = max([x.get_array().max() for x in self.axes_images])

        return minimum, maximum

    def on_button_pressed(self, event):
        if event.button == MouseButton.RIGHT:
            self.navigation_toolbar.back()
