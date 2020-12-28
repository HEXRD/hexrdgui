import copy
from functools import partial
import os
import sys

import numpy as np

from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import
import matplotlib
import matplotlib.ticker as ticker
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure

from PySide2.QtCore import (
    QObject, QSignalBlocker, QSortFilterProxyModel, Qt, Signal
)
from PySide2.QtWidgets import QFileDialog, QMenu, QSizePolicy

import hexrd.ui.constants
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.matrixutil import vecMVToSymm
from hexrd.ui.indexing.fit_grains_results_model import FitGrainsResultsModel
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader


# Sortable columns are grain id, completeness, chi^2, and t_vec_c
SORTABLE_COLUMNS = [
    *range(0, 3),
    *range(6, 9),
]


class FitGrainsResultsDialog(QObject):
    finished = Signal()

    def __init__(self, data, material=None, parent=None):
        super().__init__()

        if material is None:
            # Assume the active material is the correct one.
            # This might not actually be the case, though...
            material = HexrdConfig().active_material
            if material:
                # Warn the user so this is clear.
                print(f'Assuming material of {material.name} for stress '
                      'computations')

        self.ax = None
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.data = data
        self.data_model = FitGrainsResultsModel(data)
        self.material = material
        self.canvas = None
        self.fig = None
        self.scatter_artist = None
        self.colorbar = None

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_results_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)
        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 10)

        self.setup_tableview()
        self.load_cmaps()
        self.reset_glyph_size(update_plot=False)

        # Add column for equivalent strain
        eqv_strain = np.zeros(self.num_grains)
        for i, grain in enumerate(self.data):
            epsilon = vecMVToSymm(grain[15:21], scale=False)
            deviator = epsilon - (1/3) * np.trace(epsilon) * np.identity(3)
            eqv_strain[i] = 2 * np.sqrt(np.sum(deviator**2)) / 3
        # Reshape so we can hstack it
        self.data = np.hstack((self.data, eqv_strain[:, np.newaxis]))

        self.setup_gui()

    def setup_gui(self):
        self.update_selectors()
        self.setup_plot()
        self.setup_toolbar()
        self.setup_view_direction_options()
        self.setup_connections()
        self.update_plot()
        self.backup_ranges()
        self.update_ranges_gui()
        self.update_enable_states()

    @property
    def num_grains(self):
        return self.data.shape[0]

    @property
    def converted_data(self):
        # Perform conversions on the data to the specified types.
        # For instance, use stress instead of strain if that is set.
        tensor_type = self.tensor_type
        data = copy.deepcopy(self.data)

        if tensor_type == 'stress':
            for grain in data:
                # Convert strain to stress
                # Multiply last three numbers by factor of 2
                grain[18:21] *= 2
                grain[15:21] = np.dot(self.compliance, grain[15:21])

                # Compute the equivalent stress
                sigma = vecMVToSymm(grain[15:21], scale=False)
                deviator = sigma - (1/3) * np.trace(sigma) * np.identity(3)
                grain[21] = 3 * np.sqrt(np.sum(deviator**2)) / 2

        return data

    @property
    def stiffness(self):
        try:
            # Any of these could be an attribute error
            return self.material.unitcell.stiffness
        except AttributeError:
            return None

    @property
    def compliance(self):
        try:
            # Any of these could be an attribute error
            return self.material.unitcell.compliance
        except AttributeError:
            return None

    def update_enable_states(self):
        has_stiffness = self.stiffness is not None
        self.ui.convert_strain_to_stress.setEnabled(has_stiffness)

    def clear_artists(self):
        # Colorbar must be removed before the scatter artist
        if self.colorbar is not None:
            self.colorbar.remove()
            self.colorbar = None

        if self.scatter_artist is not None:
            self.scatter_artist.remove()
            self.scatter_artist = None

    def on_colorby_changed(self):
        self.update_plot()

    def update_plot(self):
        column = self.ui.plot_color_option.currentData()
        colors = self.converted_data[:, column]

        coords = self.data[:, 6:9]
        sz = self.ui.glyph_size_slider.value()

        # I could not find a way to update scatter plot marker colors and
        # the colorbar mappable. So we must re-draw both from scratch...
        self.clear_artists()
        self.scatter_artist = self.ax.scatter3D(*coords, c=colors,
                                                cmap=self.cmap, s=sz)
        self.colorbar = self.fig.colorbar(self.scatter_artist, shrink=0.8)
        self.draw()

    def on_export_button_pressed(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Fit-Grains Results', HexrdConfig().working_dir,
            'Output files (*.out)|All files(*.*)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            name, ext = os.path.splitext(selected_file)
            if not ext:
                selected_file += '.out'

            self.data_model.save(selected_file)

    def on_sort_indicator_changed(self, index, order):
        """Shows sort indicator for sortable columns, hides for all others."""
        horizontal_header = self.ui.table_view.horizontalHeader()
        if index in SORTABLE_COLUMNS:
            horizontal_header.setSortIndicatorShown(True)
            horizontal_header.setSortIndicator(index, order)
        else:
            horizontal_header.setSortIndicatorShown(False)

    @property
    def projection(self):
        name_map = {
            'Perspective': 'persp',
            'Orthographic': 'ortho'
        }
        return name_map[self.ui.projection.currentText()]

    def projection_changed(self):
        self.ax.set_proj_type(self.projection)
        self.draw()

    def setup_connections(self):
        self.ui.export_button.clicked.connect(self.on_export_button_pressed)
        self.ui.projection.currentIndexChanged.connect(self.projection_changed)
        self.ui.plot_color_option.currentIndexChanged.connect(
            self.on_colorby_changed)
        self.ui.hide_axes.toggled.connect(self.update_axis_visibility)
        self.ui.finished.connect(self.finished)
        self.ui.color_maps.currentIndexChanged.connect(self.update_cmap)
        self.ui.glyph_size_slider.valueChanged.connect(self.update_plot)
        self.ui.reset_glyph_size.clicked.connect(self.reset_glyph_size)

        for name in ('x', 'y', 'z'):
            action = getattr(self, f'set_view_{name}')
            action.triggered.connect(partial(self.reset_view, name))

        for w in self.range_widgets:
            w.valueChanged.connect(self.update_ranges_mpl)
            w.valueChanged.connect(self.update_range_constraints)

        self.ui.reset_ranges.pressed.connect(self.reset_ranges)
        self.ui.convert_strain_to_stress.toggled.connect(
            self.convert_strain_to_stress_toggled)

    def setup_plot(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        ax = fig.add_subplot(111, projection='3d', proj_type=self.projection)
        ax.set_xlabel('X')
        ax.set_ylabel('Y')
        ax.set_zlabel('Z')
        self.ui.canvas_layout.addWidget(canvas)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def setup_toolbar(self):
        # These don't work for 3D plots
        # "None" removes the separators
        button_blacklist = [
            None,
            'Pan',
            'Zoom',
            'Subplots',
            'Customize'
        ]
        self.toolbar = NavigationToolbar(self.canvas, self.ui, False,
                                         button_blacklist)
        self.ui.toolbar_layout.addWidget(self.toolbar)
        self.ui.toolbar_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        # Make sure our ranges editor gets updated any time matplotlib
        # might have modified the ranges underneath.
        self.toolbar.after_home_callback = self.update_ranges_gui
        self.toolbar.after_back_callback = self.update_ranges_gui
        self.toolbar.after_forward_callback = self.update_ranges_gui

    def setup_view_direction_options(self):
        b = self.ui.set_view_direction

        m = QMenu(b)
        self.set_view_direction_menu = m

        self.set_view_z = m.addAction('XY')
        self.set_view_y = m.addAction('XZ')
        self.set_view_x = m.addAction('YZ')

        b.setMenu(m)

    def reset_view(self, direction):
        # The adjustment is to force the tick markers and label to
        # appear on one side.
        adjust = 1.e-5

        angles_map = {
            'x': (0, 0),
            'y': (0, 90 - adjust),
            'z': (90 - adjust, -90 - adjust)
        }
        self.ax.view_init(*angles_map[direction])

        # Temporarily hide the labels of the axis perpendicular to the
        # screen for easier viewing.
        if self.axes_visible:
            self.hide_axis(direction)

        self.draw()

        # As soon as the image is re-drawn, the perpendicular axis will
        # be visible again.
        if self.axes_visible:
            self.show_axis(direction)

    def set_axis_visible(self, name, visible):
        ax = getattr(self.ax, f'{name}axis')
        set_label_func = getattr(self.ax, f'set_{name}label')
        if visible:
            ax.set_major_locator(ticker.AutoLocator())
            set_label_func(name.upper())
        else:
            ax.set_ticks([])
            set_label_func('')

    def hide_axis(self, name):
        self.set_axis_visible(name, False)

    def show_axis(self, name):
        self.set_axis_visible(name, True)

    @property
    def axes_visible(self):
        return not self.ui.hide_axes.isChecked()

    def update_axis_visibility(self):
        for name in ('x', 'y', 'z'):
            self.set_axis_visible(name, self.axes_visible)

        self.draw()

    def update_selectors(self):
        tensor_type = self.tensor_type.capitalize()

        # Build combo boxes in code to assign columns in grains data
        items = [
            ('Completeness', 1),
            ('Goodness of Fit', 2),
            (f'Equivalent {tensor_type}', 21),
            (f'XX {tensor_type}', 15),
            (f'YY {tensor_type}', 16),
            (f'ZZ {tensor_type}', 17),
            (f'YZ {tensor_type}', 18),
            (f'XZ {tensor_type}', 19),
            (f'XY {tensor_type}', 20)
        ]

        prev_ind = self.ui.plot_color_option.currentIndex()

        blocker = QSignalBlocker(self.ui.plot_color_option)  # noqa: F841
        self.ui.plot_color_option.clear()

        for item in items:
            self.ui.plot_color_option.addItem(*item)

        del blocker

        if hasattr(self, '_first_selector_update'):
            self.ui.plot_color_option.setCurrentIndex(prev_ind)
        else:
            self._first_selector_update = True
            index = self.ui.plot_color_option.findData(21)
            self.ui.plot_color_option.setCurrentIndex(index)

    def setup_tableview(self):
        view = self.ui.table_view

        # Subclass QSortFilterProxyModel to restrict sorting by column
        class GrainsTableSorter(QSortFilterProxyModel):
            def sort(self, column, order):
                if column not in SORTABLE_COLUMNS:
                    return
                return super().sort(column, order)

        proxy_model = GrainsTableSorter(self.ui)
        proxy_model.setSourceModel(self.data_model)
        view.verticalHeader().hide()
        view.setModel(proxy_model)
        view.resizeColumnToContents(0)

        view.setSortingEnabled(True)
        view.horizontalHeader().sortIndicatorChanged.connect(
            self.on_sort_indicator_changed)
        view.sortByColumn(0, Qt.AscendingOrder)
        self.ui.table_view.horizontalHeader().setSortIndicatorShown(False)

    def show(self):
        self.ui.show()

    @property
    def tensor_type(self):
        stress = self.ui.convert_strain_to_stress.isChecked()
        return 'stress' if stress else 'strain'

    @property
    def range_widgets(self):
        widgets = []
        for name in ('x', 'y', 'z'):
            for i in range(2):
                widgets.append(getattr(self.ui, f'range_{name}_{i}'))

        return widgets

    @property
    def ranges_gui(self):
        return [w.value() for w in self.range_widgets]

    @ranges_gui.setter
    def ranges_gui(self, v):
        self.remove_range_constraints()
        for x, w in zip(v, self.range_widgets):
            w.setValue(round(x, 5))
        self.update_range_constraints()

    @property
    def ranges_mpl(self):
        vals = []
        for name in ('x', 'y', 'z'):
            lims_func = getattr(self.ax, f'get_{name}lim')
            vals.extend(lims_func())
        return vals

    @ranges_mpl.setter
    def ranges_mpl(self, v):
        for i, name in enumerate(('x', 'y', 'z')):
            lims = (v[i * 2], v[i * 2 + 1])
            set_func = getattr(self.ax, f'set_{name}lim')
            set_func(*lims)

        # Update the navigation stack so the home/back/forward
        # buttons will know about the range change.
        self.toolbar.push_current()

        self.draw()

    def update_ranges_mpl(self):
        self.ranges_mpl = self.ranges_gui

    def update_ranges_gui(self):
        blocked = [QSignalBlocker(w) for w in self.range_widgets]  # noqa: F841
        self.ranges_gui = self.ranges_mpl

    def backup_ranges(self):
        self._ranges_backup = self.ranges_mpl

    def reset_ranges(self):
        self.ranges_mpl = self._ranges_backup
        self.update_ranges_gui()

    def convert_strain_to_stress_toggled(self):
        self.update_selectors()
        self.update_plot()

    def remove_range_constraints(self):
        widgets = self.range_widgets
        for w1, w2 in zip(widgets[0::2], widgets[1::2]):
            w1.setMaximum(sys.float_info.max)
            w2.setMinimum(sys.float_info.min)

    def update_range_constraints(self):
        widgets = self.range_widgets
        for w1, w2 in zip(widgets[0::2], widgets[1::2]):
            w1.setMaximum(w2.value())
            w2.setMinimum(w1.value())

    def load_cmaps(self):
        cmaps = sorted(i[:-2] for i in dir(matplotlib.cm) if i.endswith('_r'))
        self.ui.color_maps.addItems(cmaps)

        # Set the combobox to be the default
        self.ui.color_maps.setCurrentText(hexrd.ui.constants.DEFAULT_CMAP)

    def update_cmap(self):
        # Get the Colormap object from the name
        self.cmap = matplotlib.cm.get_cmap(self.ui.color_maps.currentText())
        self.update_plot()

    def reset_glyph_size(self, update_plot=True):
        default = matplotlib.rcParams['lines.markersize'] ** 3
        self.ui.glyph_size_slider.setSliderPosition(default)
        if update_plot:
            self.update_plot()

    def draw(self):
        self.canvas.draw()


if __name__ == '__main__':
    from PySide2.QtCore import QCoreApplication
    from PySide2.QtWidgets import QApplication

    # User specifies grains.out file
    if (len(sys.argv) < 2):
        print()
        print('Load grains.out file and display as table')
        print('Usage: python fit_grains_resuls_model.py  <path-to-grains.out>')
        print()
        sys.exit(-1)

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)

    data = np.loadtxt(sys.argv[1])

    dialog = FitGrainsResultsDialog(data)

    # For the sample, don't make it a Qt tool
    flags = dialog.ui.windowFlags()
    dialog.ui.setWindowFlags(flags & ~Qt.Tool)

    dialog.ui.resize(1200, 800)
    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec_()
