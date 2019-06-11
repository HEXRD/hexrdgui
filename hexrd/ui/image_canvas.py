import math
import os

from matplotlib.backends.backend_qt5agg import (
    FigureCanvas, NavigationToolbar2QT
)
from matplotlib.backend_bases import MouseButton
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

import fabio

from hexrd.ui.calibration_plot import create_calibration_image
import hexrd.ui.constants

class ImageCanvas(FigureCanvas):

    def __init__(self, parent=None, image_files=None):
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

        if image_files is not None:
            self.load_images(image_files)

    def __del__(self):
        # This is so that the figure can be cleaned up
        plt.close(self.figure)

    def load_images(self, image_files):
        self.figure.clear()
        self.axes_images.clear()

        cols = 1
        if len(image_files) > 1:
            cols = 2

        rows = math.ceil(len(image_files) / cols)

        for i, file in enumerate(image_files):
            img = fabio.open(file).data

            axis = self.figure.add_subplot(rows, cols, i + 1)
            axis.set_title(os.path.basename(file))
            self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                                norm=self.norm))

        self.figure.tight_layout()
        self.draw()

    def show_calibration(self, config, image_files):
        self.figure.clear()
        self.axes_images.clear()

        images = []
        for file in image_files:
            images.append(fabio.open(file).data)

        material = config.get_active_material()

        img, ring_data = create_calibration_image(config.config, images,
                                                  material.planeData)

        axis = self.figure.add_subplot(111)
        for pr in ring_data:
            axis.plot(pr[:, 1], pr[:, 0], 'c.', ms=2)

        self.axes_images.append(axis.imshow(img, cmap=self.cmap,
                                            norm=self.norm))

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

def main():
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    image_files = ['0.tiff', '1.tiff', '2.tiff', '3.tiff']

    images = ImageCanvas(image_files=image_files)
    images.show()

    # start event processing
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
