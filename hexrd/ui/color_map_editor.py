import copy

from matplotlib import cm
import matplotlib.colors

import numpy as np

import hexrd.ui.constants
from hexrd.ui.ui_loader import UiLoader


class ColorMapEditor:

    def __init__(self, image_object, parent=None):
        # The image_object can be any object with the following functions:
        # 1. set_cmap: a function to set the cmap on the image
        # 2. set_norm: a function to set the norm on the image

        self.image_object = image_object

        loader = UiLoader()
        self.ui = loader.load_file('color_map_editor.ui', parent)

        self.bounds = (0, 16384)

        self.load_cmaps()

        self.setup_connections()

    def load_cmaps(self):
        cmaps = sorted(i[:-2] for i in dir(cm) if i.endswith('_r'))
        self.ui.color_map.addItems(cmaps)

        # Set the combobox to be the default
        self.ui.color_map.setCurrentText(hexrd.ui.constants.DEFAULT_CMAP)

    def setup_connections(self):
        self.ui.maximum.valueChanged.connect(self.update_mins_and_maxes)
        self.ui.minimum.valueChanged.connect(self.update_mins_and_maxes)

        self.ui.color_map.currentIndexChanged.connect(self.update_cmap)
        self.ui.reverse.toggled.connect(self.update_cmap)
        self.ui.show_under.toggled.connect(self.update_cmap)
        self.ui.show_over.toggled.connect(self.update_cmap)

        self.ui.maximum.valueChanged.connect(self.update_norm)
        self.ui.minimum.valueChanged.connect(self.update_norm)
        self.ui.reset_range.pressed.connect(self.reset_range)
        self.ui.log_scale.toggled.connect(self.update_norm)

    def update_mins_and_maxes(self):
        # We can't do this in PySide2 for some reason:
        # self.ui.maximum.valueChanged.connect(self.ui.minimum.setMaximum)
        # self.ui.minimum.valueChanged.connect(self.ui.maximum.setMinimum)
        self.ui.maximum.setMinimum(self.ui.minimum.value())
        self.ui.minimum.setMaximum(self.ui.maximum.value())

    def update_bounds(self, data):
        bounds = self.percentile_range(data)
        self.ui.minimum.setValue(bounds[0])
        self.ui.minimum.setToolTip('Min: ' + str(bounds[0]))
        self.ui.maximum.setValue(bounds[1])
        self.ui.maximum.setToolTip('Max: ' + str(bounds[1]))

        self.bounds = bounds

    @staticmethod
    def percentile_range(data, low=69.0, high=99.9):
        if isinstance(data, dict):
            values = data.values()
        elif not isinstance(data, (list, tuple)):
            values = [data]

        l = min([np.nanpercentile(v, low) for v in values])
        h = min([np.nanpercentile(v, high) for v in values])

        if h - l < 5:
            h = l + 5

        print('Range to be used: ', l, ' -> ', h)

        return l, h

    def reset_range(self):
        if self.ui.minimum.maximum() < self.bounds[0]:
            # Make sure we can actually set the value...
            self.ui.minimum.setMaximum(self.bounds[0])

        self.ui.minimum.setValue(self.bounds[0])
        self.ui.maximum.setValue(self.bounds[1])

    def update_cmap(self):
        # Get the Colormap object from the name
        cmap = cm.get_cmap(self.ui.color_map.currentText())

        if self.ui.reverse.isChecked():
            cmap = cmap.reversed()

        # For set_under() and set_over(), we don't want to edit the
        # original color map, so make a copy
        cmap = copy.copy(cmap)

        if self.ui.show_under.isChecked():
            cmap.set_under('b')

        if self.ui.show_over.isChecked():
            cmap.set_over('r')

        self.image_object.set_cmap(cmap)

    def update_norm(self):
        min = self.ui.minimum.value()
        max = self.ui.maximum.value()

        if self.ui.log_scale.isChecked():
            # The min cannot be 0 here, or this will raise an exception
            min = 1.e-8 if min < 1.e-8 else min
            norm = matplotlib.colors.LogNorm(vmin=min, vmax=max)
        else:
            norm = matplotlib.colors.Normalize(vmin=min, vmax=max)

        self.image_object.set_norm(norm)
