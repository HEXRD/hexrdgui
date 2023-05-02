import copy
from functools import partial
import os
from pathlib import Path
import sys

import numpy as np

from mpl_toolkits.mplot3d import Axes3D, proj3d  # noqa: F401 unused import
import matplotlib
import matplotlib.ticker as ticker
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure

from PySide2.QtCore import QObject, QTimer, Qt, Signal
from PySide2.QtWidgets import QFileDialog, QMenu, QMessageBox, QSizePolicy

from hexrd.matrixutil import vecMVToSymm
from hexrd.rotations import rotMatOfExpMap

from hexrd.ui import constants
from hexrd.ui.async_runner import AsyncRunner
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.grains_table_model import GrainsTableModel
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


COORDS_SLICE = slice(6, 9)
ELASTIC_SLICE = slice(15, 21)
ELASTIC_OFF_DIAGONAL_SLICE = slice(18, 21)
EQUIVALENT_IND = 21
HYDROSTATIC_IND = 22
END_COLUMNS_IND = 23
COLOR_ORIENTATIONS_IND = 23


class FitGrainsResultsDialog(QObject):
    finished = Signal()

    def __init__(self, data, material=None, parent=None,
                 allow_export_workflow=True):
        super().__init__(parent)

        if material is None:
            # Assume the active material is the correct one.
            # This might not actually be the case, though...
            material = HexrdConfig().active_material
            if material:
                # Warn the user so this is clear.
                print(f'Assuming material of {material.name} for needed '
                      'computations')

        self.async_runner = AsyncRunner(parent)

        self.ax = None
        self.cmap = HexrdConfig().default_cmap
        self.data = data
        self.data_model = GrainsTableModel(data)
        self.material = material
        self.canvas = None
        self.fig = None
        self.scatter_artist = None
        self.highlight_artist = None
        self.colorbar = None

        loader = UiLoader()
        self.ui = loader.load_file('fit_grains_results_dialog.ui', parent)

        self.ui.splitter.setStretchFactor(0, 1)
        self.ui.splitter.setStretchFactor(1, 10)
        self.ui.export_workflow.setEnabled(allow_export_workflow)
        if not allow_export_workflow:
            # Give some possible reasons
            self.ui.export_workflow.setToolTip(
                'Currently only supported if a full HEDM workflow was '
                'performed (including indexing) and the quaternion '
                'generation method was a seed search.'
            )

        self.setup_tableview()
        self.load_cmaps()
        self.reset_glyph_size(update_plot=False)

        self.add_extra_data_columns()

        self.setup_gui()

    def add_extra_data_columns(self):
        # Add columns for equivalent strain and hydrostatic strain
        eqv_strain = np.zeros(self.num_grains)
        hydrostatic_strain = np.zeros(self.num_grains)
        for i, grain in enumerate(self.data):
            epsilon = vecMVToSymm(grain[ELASTIC_SLICE], scale=False)
            deviator = epsilon - (1/3) * np.trace(epsilon) * np.identity(3)
            eqv_strain[i] = 2 * np.sqrt(np.sum(deviator**2)) / 3
            hydrostatic_strain[i] = 1 / 3 * np.trace(epsilon)

        self.data = np.hstack((self.data, eqv_strain[:, np.newaxis]))
        self.data = np.hstack((self.data, hydrostatic_strain[:, np.newaxis]))

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

        if self.cylindrical_reference:
            for grain in data:
                x, y, z = grain[COORDS_SLICE]
                rho = np.sqrt(x**2 + z**2)
                phi = np.arctan2(z, x)
                grain[COORDS_SLICE] = (rho, phi, y)

        if tensor_type == 'stress':
            for grain in data:
                # Convert strain to stress
                # Multiply last three numbers by factor of 2
                grain[ELASTIC_OFF_DIAGONAL_SLICE] *= 2
                grain[ELASTIC_SLICE] = np.dot(self.compliance,
                                              grain[ELASTIC_SLICE])

                # Compute the equivalent stress
                sigma = vecMVToSymm(grain[ELASTIC_SLICE], scale=False)
                deviator = sigma - (1/3) * np.trace(sigma) * np.identity(3)
                grain[EQUIVALENT_IND] = 3 * np.sqrt(np.sum(deviator**2)) / 2

                # Compute the hydrostatic stress
                grain[HYDROSTATIC_IND] = 1 / 3 * np.trace(sigma)

        self._converted_data = data
        return data

    @property
    def axes_labels(self):
        if self.cylindrical_reference:
            return ('ρ', 'φ', 'Y')
        return ('X', 'Y', 'Z')

    @property
    def cylindrical_reference(self):
        return self.ui.cylindrical_reference.isChecked()

    @cylindrical_reference.setter
    def cylindrical_reference(self, v):
        self.ui.cylindricalreference.setChecked(v)

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

    @property
    def color_by_column(self):
        return self.ui.plot_color_option.currentData()

    @property
    def colors(self):
        data = self._converted_data
        column = self.color_by_column
        if column < END_COLUMNS_IND:
            return data[:, column]

        def to_colors():
            exp_maps = data[:, 3:6]
            rmats = np.array([rotMatOfExpMap(x) for x in exp_maps])
            return self.material.unitcell.color_orientations(rmats)

        funcs = {
            COLOR_ORIENTATIONS_IND: to_colors,
        }

        return funcs[column]()

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

        if self.highlight_artist is not None:
            self.highlight_artist.remove()
            self.highlight_artist = None

    def on_colorby_changed(self):
        self.update_plot()

    @property
    def glyph_size(self):
        return self.ui.glyph_size_slider.value()

    def update_plot(self):
        data = self.converted_data
        colors = self.colors

        coords = data[:, COORDS_SLICE].T

        # I could not find a way to update scatter plot marker colors and
        # the colorbar mappable. So we must re-draw both from scratch...
        self.clear_artists()
        kwargs = {
            'c': colors,
            'cmap': self.cmap,
            's': self.glyph_size,
            'depthshade': self.depth_shading,
            'picker': True,
        }
        self.scatter_artist = self.ax.scatter3D(*coords, **kwargs)
        self.update_color_settings()
        self.highlight_selected_grains()
        self.draw_idle()

    def update_color_settings(self):
        color_map_needed = self.color_by_column != COLOR_ORIENTATIONS_IND
        self.ui.color_map_label.setEnabled(color_map_needed)
        self.ui.color_maps.setEnabled(color_map_needed)

        if color_map_needed:
            self.colorbar = self.fig.colorbar(self.scatter_artist, shrink=0.8)

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

    def on_export_stresses_button_pressed(self):
        if self.tensor_type != 'stress':
            raise Exception('Tensor type must be stress')

        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Fit-Grains Stresses', HexrdConfig().working_dir,
            'Npz Files (*.npz)')

        if not selected_file:
            return

        stresses = self.converted_data[:, ELASTIC_SLICE]
        HexrdConfig().working_dir = str(Path(selected_file).parent)
        ext = Path(selected_file).suffix
        if ext != '.npz':
            selected_file += '.npz'

        np.savez_compressed(selected_file, stresses=stresses)

    @property
    def depth_shading(self):
        return self.ui.depth_shading.isChecked()

    @depth_shading.setter
    def depth_shading(self, v):
        self.ui.depth_shading.setChecked(v)

    @property
    def projection(self):
        name_map = {
            'Perspective': 'persp',
            'Orthographic': 'ortho'
        }
        return name_map[self.ui.projection.currentText()]

    def projection_changed(self):
        self.ax.set_proj_type(self.projection)
        self.draw_idle()

    def cylindrical_reference_toggled(self):
        self.update_axes_labels()
        self.update_plot()

    def setup_connections(self):
        self.ui.export_button.clicked.connect(self.on_export_button_pressed)
        self.ui.export_stresses.clicked.connect(
            self.on_export_stresses_button_pressed)
        self.ui.projection.currentIndexChanged.connect(self.projection_changed)
        self.ui.plot_color_option.currentIndexChanged.connect(
            self.on_colorby_changed)
        self.ui.hide_axes.toggled.connect(self.update_axis_visibility)
        self.ui.depth_shading.toggled.connect(self.update_plot)
        self.ui.finished.connect(self.finished)
        self.ui.color_maps.currentIndexChanged.connect(self.update_cmap)
        self.ui.glyph_size_slider.valueChanged.connect(self.update_plot)
        self.ui.reset_glyph_size.clicked.connect(self.reset_glyph_size)
        self.ui.cylindrical_reference.toggled.connect(
            self.cylindrical_reference_toggled)
        self.ui.export_workflow.clicked.connect(
            self.on_export_workflow_clicked)

        for name in ('x', 'y', 'z'):
            action = getattr(self, f'set_view_{name}')
            action.triggered.connect(partial(self.reset_view, name))

        for w in self.range_widgets:
            w.valueChanged.connect(self.update_ranges_mpl)
            w.valueChanged.connect(self.update_range_constraints)

        self.ui.reset_ranges.pressed.connect(self.reset_ranges)
        self.ui.convert_strain_to_stress.toggled.connect(
            self.convert_strain_to_stress_toggled)

        self.data_model.grains_table_modified.connect(
            self.on_grains_table_modified)

        self.ui.table_view.selection_changed.connect(self.selection_changed)

    def setup_plot(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        canvas.mpl_connect('pick_event', self.point_picked)

        kwargs = {
            'projection': '3d',
            'proj_type': self.projection,
            # Do not compute the z order so we can make highlighted points
            # always appear in front.
            'computed_zorder': False,
        }
        ax = canvas.figure.add_subplot(111, **kwargs)

        # Set default limits to -0.5 to 0.5
        for name in ('x', 'y', 'z'):
            func = getattr(ax, f'set_{name}lim')
            func(-0.5, 0.5)

        self.ui.canvas_layout.addWidget(canvas)

        self.fig = canvas.figure
        self.ax = ax
        self.canvas = canvas

        self.update_axes_labels()

    def point_picked(self, event):
        # Unfortunately, in matplotlib 3d, the indices change
        # depending on the current orientation of the plot.
        # We can find the picked point, however, by transforming
        # the 3D data into 2D points (as they are displayed on the screen),
        # and finding which data point is the closest to the mouse click.

        # This code was largely inspired by:
        # https://stackoverflow.com/a/66926265

        xx = event.mouseevent.x
        yy = event.mouseevent.y

        proj = self.ax.get_proj()
        data = self.converted_data[:, COORDS_SLICE]

        ind = 0
        dmin = np.inf
        for i, (x, y, z) in enumerate(data):
            # Transform the 3D data points into 2D points on the screen,
            # then find the closest point.
            x2, y2, z2 = proj3d.proj_transform(x, y, z, proj)
            x3, y3 = self.ax.transData.transform((x2, y2))

            # Compute the distance
            d = np.sqrt((x3 - xx)**2 + (y3 - yy)**2)

            if d < dmin:
                dmin = d
                ind = i

        self.select_grain_in_table(ind)

    def select_grain_in_table(self, grain_id):
        table_model = self.ui.table_view.model()
        for i in range(self.data_model.rowCount()):
            if grain_id == table_model.index(i, 0).data():
                return self.select_row(i)

        raise Exception(f'Failed to find grain_id {grain_id} in table')

    def select_row(self, i):
        if i is None or i >= self.data_model.rowCount():
            # Out of range. Don't do anything.
            return

        # Select the row
        self.ui.table_view.selectRow(i)

    def selection_changed(self):
        self.highlight_selected_grains()

    def highlight_selected_grains(self):
        selected_grain_ids = self.ui.table_view.selected_grain_ids

        if self.highlight_artist is not None:
            self.highlight_artist.remove()

        # Now draw the highlight markers for these selected grains
        data = self.converted_data[:, COORDS_SLICE][selected_grain_ids].T

        kwargs = {
            # Bright yellow
            'c': '#f9ff00',
            # Make highlighted glyphs slightly larger
            's': round(self.glyph_size * 1.2),
            'alpha': 1.0,
            # Make sure the highlighted glyphs are always in front
            'zorder': 1e10,
        }
        self.highlight_artist = self.ax.scatter3D(*data, **kwargs)
        self.draw_idle()

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

        self.draw_idle()

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

        self.draw_idle()

    def update_axes_labels(self):
        axes = ('x', 'y', 'z')
        labels = self.axes_labels
        for axis, label in zip(axes, labels):
            func = getattr(self.ax, f'set_{axis}label')
            func(label)

    def update_selectors(self):
        tensor_type = self.tensor_type.capitalize()

        # Build combo boxes in code to assign columns in grains data
        items = [
            ('Completeness', 1),
            ('Goodness of Fit', 2),
            (f'Equivalent {tensor_type}', EQUIVALENT_IND),
            (f'Hydrostatic {tensor_type}', HYDROSTATIC_IND),
            ('Orientation', COLOR_ORIENTATIONS_IND),
            (f'XX {tensor_type}', 15),
            (f'YY {tensor_type}', 16),
            (f'ZZ {tensor_type}', 17),
            (f'YZ {tensor_type}', 18),
            (f'XZ {tensor_type}', 19),
            (f'XY {tensor_type}', 20)
        ]

        prev_ind = self.ui.plot_color_option.currentIndex()

        with block_signals(self.ui.plot_color_option):
            self.ui.plot_color_option.clear()

            for item in items:
                self.ui.plot_color_option.addItem(*item)

        if hasattr(self, '_first_selector_update'):
            self.ui.plot_color_option.setCurrentIndex(prev_ind)
        else:
            self._first_selector_update = True
            index = self.ui.plot_color_option.findData(EQUIVALENT_IND)
            self.ui.plot_color_option.setCurrentIndex(index)

    def setup_tableview(self):
        view = self.ui.table_view

        # Update the variables on the table view
        view.data_model = self.data_model
        view.material = self.material
        view.can_modify_grains = True

    def show(self):
        self.ui.show()

    def show_later(self):
        # Call this if you might not be running on the GUI thread, so
        # show() will be called on the GUI thread.
        QTimer.singleShot(0, lambda: self.show())

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

        self.draw_idle()

    def update_ranges_mpl(self):
        self.ranges_mpl = self.ranges_gui

    def update_ranges_gui(self):
        with block_signals(*self.range_widgets):
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
        cmaps = constants.ALL_CMAPS
        self.ui.color_maps.addItems(cmaps)

        # Set the combobox to be the default
        self.ui.color_maps.setCurrentText(HexrdConfig().default_cmap)

    def update_cmap(self):
        # Get the Colormap object from the name
        self.cmap = matplotlib.cm.get_cmap(self.ui.color_maps.currentText())
        self.update_plot()

    def reset_glyph_size(self, update_plot=True):
        default = matplotlib.rcParams['lines.markersize'] ** 3
        self.ui.glyph_size_slider.setSliderPosition(default)
        if update_plot:
            self.update_plot()

    def draw_idle(self):
        self.canvas.draw_idle()

    def on_grains_table_modified(self):
        # Update our grains table
        self.data = self.data_model.full_grains_table
        self.add_extra_data_columns()
        self.update_plot()

    def _save_workflow_files(self, selected_directory):

        def full_path(file_name):
            # Convenience function to generate full path via pathlib
            return str(Path(selected_directory) / file_name)

        HexrdConfig().working_dir = selected_directory

        HexrdConfig().save_indexing_config(full_path('workflow.yml'))
        HexrdConfig().save_materials(full_path('materials.h5'))
        HexrdConfig().save_instrument_config(full_path('instrument.hexrd'))

        ims_dict = HexrdConfig().unagg_images
        for det in HexrdConfig().detector_names:
            path = full_path(f'{det}.npz')
            kwargs = {
                'ims': ims_dict.get(det),
                'name': det,
                'write_file': path,
                'selected_format': 'frame-cache',
                'cache_file': path,
                'threshold': 0,
            }
            HexrdConfig().save_imageseries(**kwargs)

    def on_export_workflow_clicked(self):
        selected_directory = QFileDialog.getExistingDirectory(
                self.ui, 'Select Directory', HexrdConfig().working_dir)

        if not selected_directory:
            # User canceled
            return

        # Warn the user if any files will be over-written
        write_files = [
            'workflow.yml',
            'materials.h5',
            'instrument.hexrd',
        ] + [f'{det}.npz' for det in HexrdConfig().detector_names]

        overwrite_files = []
        for f in write_files:
            full_path = Path(selected_directory) / f
            if full_path.exists():
                overwrite_files.append(str(full_path))

        if overwrite_files:
            msg = 'The following files will be overwritten:\n\n'
            msg += '\n'.join(overwrite_files)
            msg += '\n\nProceed?'
            response = QMessageBox.question(self.parent(), 'WARNING', msg)
            if response == QMessageBox.No:
                return

        self.async_runner.progress_title = 'Saving workflow configuration'
        self.async_runner.run(self._save_workflow_files, selected_directory)

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

    data = np.loadtxt(sys.argv[1], ndmin=2)

    dialog = FitGrainsResultsDialog(data)

    # For the sample, don't make it a Qt tool
    flags = dialog.ui.windowFlags()
    dialog.ui.setWindowFlags(flags & ~Qt.Tool)

    dialog.ui.resize(1200, 800)
    dialog.finished.connect(app.quit)
    dialog.show()
    app.exec_()
