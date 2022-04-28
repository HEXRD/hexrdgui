import copy
from pathlib import Path

from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np
import yaml

from PySide2.QtCore import (
    Signal, QItemSelectionModel, QObject, QSignalBlocker, QTimer, Qt
)
from PySide2.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox,
    QSizePolicy, QSpinBox, QTableWidgetItem
)

from hexrd.constants import sigma_to_fwhm
from hexrd.findorientations import (
    clean_map, filter_maps_if_requested, filter_stdev_DFLT
)
from hexrd.imageutil import find_peaks_2d
from hexrd.rotations import quatOfExpMap

from hexrd.ui import resource_loader

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.fiber_pick_utils import (
    _angles_from_orientation, _pick_to_fiber
)
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.select_items_widget import SelectItemsWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals

import hexrd.ui.constants
import hexrd.ui.resources.indexing


DEFAULT_FWHM = filter_stdev_DFLT * sigma_to_fwhm


class OmeMapsViewerDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ome_maps_viewer_dialog.ui', parent)

        self.data = data
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None
        self.transform = lambda x: x
        self.spots = None
        self.reset_internal_config()

        self.cached_hand_picked_spots = {}
        self.generated_fibers = np.empty((0,))
        self.current_fiber_spots = np.empty((0,))
        self.hand_picked_fibers = np.empty((0, 3))
        self.latest_picked_eta = None
        self.latest_picked_ome = None
        self.latest_picked_hkl_index = None

        self.setup_widget_paths()

        self.setup_combo_box_item_data()

        # Hide these tab bars. The user selects them via combo boxes.
        self.ui.quaternion_method_tab_widget.tabBar().hide()
        self.ui.seed_search_method_tab_widget.tabBar().hide()

        self.create_tooltips()

        self.setup_plot()
        self.setup_color_map()
        self.setup_hkls_table()

        self.update_gui()

        self.setup_connections()

        # This will trigger a re-draw and update of everything
        self.filter_modified()

    def setup_connections(self):
        self.ui.active_hkl.currentIndexChanged.connect(self.update_plot)
        self.ui.label_spots.toggled.connect(self.update_spots)
        self.ui.export_button.pressed.connect(self.on_export_button_pressed)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

        self.ui.quaternion_method.currentIndexChanged.connect(
            self.quaternion_method_changed)

        self.ui.seed_search_method.currentIndexChanged.connect(
            self.seed_search_method_changed)

        self.color_map_editor.ui.minimum.valueChanged.connect(
            self.update_config)

        self.ui.select_working_dir.pressed.connect(self.select_working_dir)

        self.select_hkls_widget.selection_changed.connect(self.update_config)

        def changed_signal(w):
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                return w.valueChanged
            elif isinstance(w, QComboBox):
                return w.currentIndexChanged
            elif isinstance(w, QCheckBox):
                return w.toggled
            else:
                raise Exception(f'Unhandled widget type: {type(w)}')

        for w in self.filter_widgets:
            changed_signal(w).connect(self.filter_modified)

        for w in self.yaml_widgets:
            changed_signal(w).connect(self.update_config)

        for w in self.seed_search_method_parameter_widgets:
            changed_signal(w).connect(self.update_spots)

        self.ui.select_quaternion_grid_file.pressed.connect(
            self.select_quaternion_grid_file)

        self.ui.current_fiber_slider.valueChanged.connect(
            self.current_fiber_slider_value_changed)

        self.ui.current_fiber_angle.valueChanged.connect(
            self.current_fiber_angle_value_changed)

        self.ui.add_fiber_button.clicked.connect(self.add_current_fiber)

        self.ui.picked_fibers_table.selectionModel().selectionChanged.connect(
            self.picked_fibers_table_selection_changed)

        self.ui.picked_fibers_delete_selected.clicked.connect(
            self.delete_selected_fiber_rows)

        self.ui.fiber_step.valueChanged.connect(
            self.synchronize_fiber_step_boxes)
        self.ui.hand_picked_fiber_step.valueChanged.connect(
            self.synchronize_fiber_step_boxes)

        self.ui.fiber_step.valueChanged.connect(self.fiber_step_value_changed)

    def setup_combo_box_item_data(self):
        # Set the item data for the combo boxes to be the names we want
        item_data = [
            'seed_search',
            'grid_search',
            'hand_picked',
        ]
        for i, data in enumerate(item_data):
            self.ui.quaternion_method.setItemData(i, data)

        item_data = [
            'label',
            'blob_dog',
            'blob_log'
        ]
        for i, data in enumerate(item_data):
            self.ui.seed_search_method.setItemData(i, data)

        item_data = [
            'dbscan',
            'sph-dbscan',
            'ort-dbscan',
            'fclusterdata'
        ]
        for i, data in enumerate(item_data):
            self.ui.clustering_algorithm.setItemData(i, data)

    def create_tooltips(self):
        tooltip = ('Full width at half maximum (FWHM) to use for the Gaussian '
                   f'Laplace filter.\nDefault: {DEFAULT_FWHM:.2f}')
        self.ui.filtering_fwhm.setToolTip(tooltip)
        self.ui.filtering_fwhm_label.setToolTip(tooltip)

    def select_quaternion_grid_file(self):
        title = 'Select quaternion grid file'
        filters = 'NPY files (*.npy)'
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, title, HexrdConfig().working_dir, filters)

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            self.quaternion_grid_file = selected_file

    def update_enable_states(self):
        filtering = self.ui.apply_filtering.isChecked()
        apply_gl = self.ui.filtering_apply_gaussian_laplace.isChecked()
        fwhm_enabled = filtering and apply_gl

        self.ui.filtering_apply_gaussian_laplace.setEnabled(filtering)
        self.ui.filtering_fwhm.setEnabled(fwhm_enabled)
        self.ui.filtering_fwhm_label.setEnabled(fwhm_enabled)

    def reset_internal_config(self):
        self.config = copy.deepcopy(HexrdConfig().indexing_config)

    def show(self):
        self.update_plot()
        self.ui.show()

    def show_later(self):
        # In case this was called in a separate thread (which will
        # happen if the maps were generated), post the show() to the
        # event loop. Otherwise, on Mac, the dialog will not move to
        # the front.
        QTimer.singleShot(0, lambda: self.show())

    def on_accepted(self):
        # Update the config just in case...
        self.update_config()
        try:
            self.validate()
        except ValidationException as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            self.ui.show()
            return

        self.save_config()
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def validate(self):
        if self.quaternion_method_name == 'hand_picked':
            if self.hand_picked_fibers.size == 0:
                msg = 'At least one fiber must be picked'
                raise ValidationException(msg)
        elif self.quaternion_method_name == 'grid_search':
            # Make sure the file exists.
            q_file = self.config['find_orientations']['use_quaternion_grid']
            if not q_file or not Path(q_file).exists():
                msg = f'Quaternion file "{q_file}" does not exist!'
                raise ValidationException(msg)

            # Load the file and validate the shape
            try:
                quats = np.load(q_file)
            except ValueError:
                msg = f'Failed to load quaternion file "{q_file}" with numpy'
                raise ValidationException(msg)

            if quats.ndim != 2 or quats.shape[0] != 4:
                msg = (
                    f'The quaternion array in "{q_file}" must have a shape of '
                    f'(4, n), but instead has a shape of "{quats.shape}".'
                )
                raise ValidationException(msg)
        elif self.quaternion_method_name == 'seed_search':
            # Seed search. Make sure hkls were chosen.
            hkls = self.config['find_orientations']['seed_search']['hkl_seeds']
            if not hkls:
                raise ValidationException('No hkls selected')
        else:
            msg = f'Unhandled quaternion method: {self.quaternion_method_name}'
            raise ValidationException(msg)

    def setup_widget_paths(self):
        text = resource_loader.load_resource(hexrd.ui.resources.indexing,
                                             'gui_config_maps.yml')
        self.gui_config_maps = yaml.load(text, Loader=yaml.FullLoader)

        paths = {}

        def recursive_get_paths(cur_config, cur_path):
            for key, value in cur_config.items():
                new_path = cur_path + [key]
                if isinstance(value, str):
                    paths[value] = new_path
                    continue

                recursive_get_paths(value, new_path)

        initial_path = []
        recursive_get_paths(self.gui_config_maps, initial_path)
        self.widget_paths = paths

    @property
    def seed_search_method_parameter_widgets(self):
        maps = self.gui_config_maps
        methods = maps['find_orientations']['seed_search']['method']
        names = [v for d in methods.values() for v in d.values()]
        return [getattr(self.ui, x) for x in names]

    @property
    def quaternion_method_name(self):
        return self.ui.quaternion_method.currentData()

    @quaternion_method_name.setter
    def quaternion_method_name(self, v):
        w = self.ui.quaternion_method
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                self.update_visibilities()
                self.update_quaternion_method_tab()
                return

        raise Exception(f'Unable to set quaternion_method: {v}')

    @property
    def quaternions_hand_picked(self):
        return self.quaternion_method_name == 'hand_picked'

    @property
    def quaternion_grid_file(self):
        return self.ui.quaternion_grid_file.text()

    @quaternion_grid_file.setter
    def quaternion_grid_file(self, v):
        self.ui.quaternion_grid_file.setText(v)

    def update_visibilities(self):
        self.update_seed_search_visibilities()
        self.update_indexing_visibilities()
        self.update_clustering_visibilities()

    @staticmethod
    def set_widgets_visible(widgets, visible):
        for w in widgets:
            w.setVisible(visible)

    def update_seed_search_visibilities(self):
        widgets = [
            self.ui.select_hkls_group,
            self.ui.label_spots,
        ]
        visible = self.quaternion_method_name == 'seed_search'

        self.set_widgets_visible(widgets, visible)

    def update_indexing_visibilities(self):
        widgets = [
            self.ui.omega_group_box,
            self.ui.eta_group_box,
        ]
        visible = self.quaternion_method_name in ('seed_search', 'grid_search')

        self.set_widgets_visible(widgets, visible)

    def update_clustering_visibilities(self):
        widgets = [
            self.ui.clustering_group_box,
        ]
        visible = self.quaternion_method_name in ('seed_search', 'grid_search')

        self.set_widgets_visible(widgets, visible)

    @property
    def seed_search_method_name(self):
        return self.ui.seed_search_method.currentData()

    @seed_search_method_name.setter
    def seed_search_method_name(self, v):
        w = self.ui.seed_search_method
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                self.update_seed_search_method_tab()
                return

        raise Exception(f'Unable to set seed_search_method: {v}')

    def filter_modified(self):
        self.update_enable_states()
        self.update_config()
        self.reset_filters()
        self.update_plot()

    @property
    def filter_widgets(self):
        return [
            self.ui.apply_filtering,
            self.ui.filtering_apply_gaussian_laplace,
            self.ui.filtering_fwhm,
        ]

    @property
    def filter_maps(self):
        if not self.ui.apply_filtering.isChecked():
            return False

        if not self.ui.filtering_apply_gaussian_laplace.isChecked():
            return True

        # Keep this as a native type...
        return float(self.ui.filtering_fwhm.value() / sigma_to_fwhm)

    @filter_maps.setter
    def filter_maps(self, v):
        if isinstance(v, bool):
            filtering = v
            apply_gl = False
            fwhm = DEFAULT_FWHM
        else:
            filtering = True
            apply_gl = True
            fwhm = v * sigma_to_fwhm

        self.ui.apply_filtering.setChecked(filtering)
        self.ui.filtering_apply_gaussian_laplace.setChecked(apply_gl)
        self.ui.filtering_fwhm.setValue(fwhm)

    def quaternion_method_changed(self):
        self.clear_generated_fibers()
        self.clear_selected_fibers_artists()
        self.select_fiber_rows([])

        self.update_quaternion_method_tab()
        self.update_visibilities()
        self.update_config()
        self.update_spots()

    def seed_search_method_changed(self):
        self.update_seed_search_method_tab()
        self.update_config()
        self.update_spots()

    def update_quaternion_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.quaternion_method_name + '_tab')
        self.ui.quaternion_method_tab_widget.setCurrentWidget(method_tab)

    def update_seed_search_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.seed_search_method_name + '_tab')
        self.ui.seed_search_method_tab_widget.setCurrentWidget(method_tab)

    @property
    def hkls(self):
        hkl_indices = self.data.iHKLList
        all_hkls = self.data.planeData.getHKLs(asStr=True)
        return [all_hkls[i] for i in hkl_indices]

    def update_hkl_options(self):
        # This won't trigger a re-draw. Can change in the future if needed.
        with block_signals(self.ui.active_hkl):
            self.ui.active_hkl.clear()
            self.ui.active_hkl.addItems(self.hkls)

    def setup_plot(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        ax = fig.add_subplot()
        ax.set_title('Eta Omega Maps')
        ax.set_xlabel(r'$\eta$ ($\deg$)')
        ax.set_ylabel(r'$\omega$ ($\deg$)')
        ax.format_coord = self.format_coord
        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        canvas.mpl_connect('button_press_event', self.plot_clicked)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def format_coord(self, x, y):
        # Format the coordinates to be displayed on the navigation toolbar.
        # The coordinates are displayed when the mouse is moved.
        float_format = '8.3f'
        delimiter = ',  '
        prefix = '   '

        labels = []
        labels.append(f'eta = {x:{float_format}}')
        labels.append(f'omega = {y:{float_format}}')

        return prefix + delimiter.join(labels)

    def setup_color_map(self):
        self.color_map_editor = ColorMapEditor(self, self.ui)
        self.ui.color_map_editor_layout.addWidget(self.color_map_editor.ui)
        self.update_cmap_bounds()

        # Set the initial max as 20
        self.color_map_editor.ui.maximum.setValue(20)

    def setup_hkls_table(self):
        selected = self.config['find_orientations']['seed_search']['hkl_seeds']
        hkls = self.hkls
        items = [(x, i in selected) for i, x in enumerate(hkls)]
        self.select_hkls_widget = SelectItemsWidget(items, self.ui)
        layout = self.ui.select_hkls_widget_layout
        layout.addWidget(self.select_hkls_widget.ui)

    @property
    def selected_hkls(self):
        return self.select_hkls_widget.selected_indices

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, d):
        if hasattr(self, '_data') and d == self._data:
            return

        self.raw_data = copy.deepcopy(d)

        # This data will have filters applied to it
        # We will make a shallow copy, and deep copy the data store
        # when filters are applied.
        self._data = copy.copy(self.raw_data)
        self.reset_filters()

        self.update_extent()
        self.update_cmap_bounds()

    @property
    def scaled_image_data(self):
        return self.transform(self.image_data)

    @property
    def image_data(self):
        return self.data.dataStore[self.current_hkl_index]

    def update_extent(self):
        etas = np.degrees(self.data.etas)
        omes = np.degrees(self.data.omegas)
        self.extent = (etas[0], etas[-1], omes[-1], omes[0])

    def update_cmap_bounds(self):
        if not hasattr(self, 'color_map_editor'):
            return

        self.color_map_editor.update_bounds(self.scaled_image_data)

        w = self.color_map_editor.ui.minimum
        w.setStyleSheet('background-color: yellow')
        note = 'NOTE: this is used to set find_orientations:threshold'
        if note not in w.toolTip():
            w.setToolTip(f'{w.toolTip()}\n\n{note}')

    @property
    def display_spots(self):
        return all((
            self.quaternion_method_name == 'seed_search',
            self.ui.label_spots.isChecked(),
        ))

    def clear_spot_lines(self):
        if hasattr(self, '_spot_lines'):
            self._spot_lines.remove()
            del self._spot_lines

    def update_spots(self):
        self.clear_spot_lines()
        if not self.display_spots:
            self.draw()
            return

        self.create_spots()
        if self.spots.size:
            kwargs = {
                'x': self.spots[:, 1],
                'y': self.spots[:, 0],
                's': 18,
                'c': 'm',
                'marker': '+',
            }
            self._spot_lines = self.ax.scatter(**kwargs)

        self.draw()

    def update_plot(self):
        ax = self.ax

        data = self.scaled_image_data
        if not hasattr(self, 'im'):
            im = ax.imshow(data)
            self.im = im
            self.original_extent = im.get_extent()
        else:
            im = self.im
            im.set_data(data)

        im.set_cmap(self.cmap)
        im.set_norm(self.norm)

        self.update_spots()
        self.update_current_fiber_plot()
        self.draw_selected_fibers()

        im.set_extent(self.extent)

        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')

        # Now disable autoscaling
        ax.autoscale(False)

        self.draw()

    def draw(self):
        self.fig.canvas.draw()

    @property
    def current_hkl_index(self):
        return self.ui.active_hkl.currentIndex()

    def set_cmap(self, cmap):
        self.cmap = cmap
        if hasattr(self, 'im'):
            self.im.set_cmap(cmap)
            self.draw()

    def set_norm(self, norm):
        self.norm = norm
        if hasattr(self, 'im'):
            self.im.set_norm(norm)
            self.draw()

    def set_scaling(self, transform):
        self.transform = transform
        self.update_plot()

    def create_spots(self):
        # We will clean the data for spot labeling, so make a deep copy
        data = copy.deepcopy(self.image_data)
        clean_map(data)

        method_name = self.seed_search_method_name
        method_dict = self.config['find_orientations']['seed_search']['method']
        method_kwargs = method_dict[method_name]

        _, spots = find_peaks_2d(data, method_name, method_kwargs)

        if spots.size:
            # Rescale the points to match the extents
            old_extent = self.original_extent
            old_x_range = (old_extent[0], old_extent[1])
            old_y_range = (old_extent[3], old_extent[2])
            new_x_range = (self.extent[0], self.extent[1])
            new_y_range = (self.extent[3], self.extent[2])

            spots[:, 1] = np.interp(spots[:, 1], old_x_range, new_x_range)
            spots[:, 0] = np.interp(spots[:, 0], old_y_range, new_y_range)

        self.spots = spots

    def on_export_button_pressed(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Eta Omega Maps', HexrdConfig().working_dir,
            'NPZ files (*.npz)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            if not selected_file.endswith('.npz'):
                selected_file += '.npz'

            # Save the raw data out...
            self.raw_data.save(selected_file)

    def select_working_dir(self):
        caption = 'Select directory to write scored orientations to'
        d = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=self.working_dir)

        if d:
            self.working_dir = d

    @property
    def threshold(self):
        return self.color_map_editor.ui.minimum.value()

    @threshold.setter
    def threshold(self, v):
        if self.color_map_editor.ui.maximum.value() <= v:
            # Move the maximum so we can set the minimum also
            self.color_map_editor.ui.maximum.setValue(v + 1)

        self.color_map_editor.ui.minimum.setValue(v)

    @property
    def write_scored_orientations(self):
        return self.ui.write_scored_orientations.isChecked()

    @write_scored_orientations.setter
    def write_scored_orientations(self, v):
        self.ui.write_scored_orientations.setChecked(v)

    @property
    def yaml_widgets(self):
        return [getattr(self.ui, x) for x in self.widget_paths.keys()]

    @property
    def all_widgets(self):
        return self.yaml_widgets + self.filter_widgets + [
            self.ui.quaternion_method,
            self.ui.quaternion_method_tab_widget,
            self.ui.seed_search_method,
            self.ui.seed_search_method_tab_widget,
            self.ui.active_hkl
        ]

    def update_gui(self):
        # Updates all of the widgets with their settings from the config
        self.update_hkl_options()
        blockers = [QSignalBlocker(x) for x in self.all_widgets]  # noqa: F841

        def setter(w):
            if isinstance(w, QComboBox):
                return lambda x: w.setCurrentIndex(w.findData(x))

            # Assume it is a spin box of some kind
            return w.setValue

        config = self.config

        def set_val(w, path):
            cur = config
            for x in path:
                if x not in cur:
                    # If it's not in the config, skip over it
                    return
                cur = cur[x]

            setter(w)(cur)

        for w, path in self.widget_paths.items():
            w = getattr(self.ui, w)
            set_val(w, path)

        find_orientations = config['find_orientations']

        if find_orientations.get('_hand_picked_quaternions', False):
            self.quaternion_method_name = 'hand_picked'
        elif find_orientations['use_quaternion_grid']:
            self.quaternion_method_name = 'grid_search'
        else:
            self.quaternion_method_name = 'seed_search'

        self.quaternion_grid_file = find_orientations.get('_quat_file', '')

        # Update the method name
        method = find_orientations['seed_search']['method']
        self.seed_search_method_name = next(iter(method))

        # Also set the color map minimum to the threshold value...
        self.threshold = find_orientations['threshold']

        self.filter_maps = find_orientations['orientation_maps']['filter_maps']

        key = '_write_scored_orientations'
        self.write_scored_orientations = find_orientations.get(key, False)

        self.working_dir = config.get('working_dir', HexrdConfig().working_dir)

        self.synchronize_fiber_step_boxes(self.fiber_step)

        self.ui.current_fiber_slider.setRange(
            0, self.num_hand_picked_fibers - 1)

    def update_config(self):
        # Update all of the config with their settings from the widgets
        config = self.config
        find_orientations = config['find_orientations']

        key = '_hand_picked_quaternions'
        find_orientations[key] = self.quaternions_hand_picked

        if self.quaternion_method_name == 'grid_search':
            quat_file = self.quaternion_grid_file
        else:
            quat_file = None
        find_orientations['use_quaternion_grid'] = quat_file
        find_orientations['_quat_file'] = self.quaternion_grid_file

        # Clear the method so it can be set to a different one
        method = find_orientations['seed_search']['method']
        method.clear()

        # Give it some dummy contents so the setter below will run
        method_name = self.seed_search_method_name
        dummy_method = (
            self.gui_config_maps['find_orientations']['seed_search']['method'])
        method[method_name] = copy.deepcopy(dummy_method[method_name])

        def getter(w):
            if isinstance(w, QComboBox):
                return w.currentData

            # Assume it is a spin box of some kind
            return w.value

        def set_val(val, path):
            cur = config
            for x in path[:-1]:
                if x not in cur:
                    # If it's not in the config, skip over it
                    return
                cur = cur[x]

            cur[path[-1]] = val

        for w, path in self.widget_paths.items():
            w = getattr(self.ui, w)
            val = getter(w)()
            set_val(val, path)

        # Also set the threshold to the minimum color map value...
        find_orientations['threshold'] = self.threshold
        find_orientations['seed_search']['hkl_seeds'] = self.selected_hkls
        find_orientations['orientation_maps']['filter_maps'] = self.filter_maps

        key = '_write_scored_orientations'
        find_orientations[key] = self.write_scored_orientations

        config['working_dir'] = self.working_dir

    def save_config(self):
        HexrdConfig().config['indexing'] = copy.deepcopy(self.config)

    def reset_filters(self):
        # Reset the data store
        if hasattr(self.data, '_dataStore'):
            name = '_dataStore'
        else:
            name = 'dataStore'
        setattr(self.data, name, copy.deepcopy(self.raw_data.dataStore))

        # Make a fake config to pass to hexrd
        class Cfg:
            pass

        path = ['find_orientations', 'orientation_maps', 'filter_maps']
        cfg = Cfg()
        cur = cfg
        for name in path[:-1]:
            setattr(cur, name, Cfg())
            cur = getattr(cur, name)

        setattr(cur, path[-1], self.filter_maps)

        # Perform the filtering
        filter_maps_if_requested(self.data, cfg)

    def clear_generated_fibers(self):
        # Reset the latest picks to None
        self.latest_picked_eta = None
        self.latest_picked_ome = None
        self.latest_picked_hkl_index = None

        self.generated_fibers = np.empty((0,))
        self.ui.current_fiber_slider.setValue(0)
        # In case the value didn't change. This shouldn't be expensive,
        # so it's okay to run it twice.
        self.update_current_fiber()

    def plot_clicked(self, event):
        if not self.quaternions_hand_picked:
            # If we are not hand picking quaternions, just return
            return

        if not event.button == 3:
            # Hand-picking quaternions is right-click only
            return

        self.latest_picked_eta = event.xdata
        self.latest_picked_ome = event.ydata
        self.latest_picked_hkl_index = self.current_hkl_index

        self.recreate_generated_fibers()

    def recreate_generated_fibers(self):
        pick_coords = (self.latest_picked_eta, self.latest_picked_ome)
        if any(x is None for x in pick_coords):
            # No picked coords. Just return.
            return

        hkl_index = self.latest_picked_hkl_index
        if hkl_index is None or hkl_index >= len(self.data.dataStore):
            # Invalid hkl index. Return.
            return

        instr = create_hedm_instrument()

        kwargs = {
            'pick_coords': pick_coords,
            'eta_ome_maps': self.data,
            'map_index': hkl_index,
            'step': self.fiber_step,
            'beam_vec': instr.beam_vector,
            'chi': instr.chi,
            'as_expmap': True,
        }
        self.generated_fibers = _pick_to_fiber(**kwargs)

        self.ui.current_fiber_slider.setValue(0)
        # In case the value didn't change. This shouldn't be expensive,
        # so it's okay to run it twice.
        self.update_current_fiber()

    def update_current_fiber(self):
        enable = len(self.generated_fibers) > 0

        enable_list = [
            self.ui.current_fiber_slider,
            self.ui.current_fiber_angle,
            self.ui.selected_fiber_orientation_0,
            self.ui.selected_fiber_orientation_1,
            self.ui.selected_fiber_orientation_2,
            self.ui.add_fiber_button,
        ]
        for w in enable_list:
            w.setEnabled(enable)

        for i, v in enumerate(self.current_fiber_orientation):
            w = getattr(self.ui, f'selected_fiber_orientation_{i}')
            w.setValue(v)

        angle = self.current_fiber_index * self.fiber_step
        self.ui.current_fiber_angle.setValue(angle)

        self.generate_current_fiber_spots()
        self.update_current_fiber_plot()

    def generate_current_fiber_spots(self):
        if self.current_fiber_index >= len(self.generated_fibers):
            fibers = []
        else:
            fibers = self.generated_fibers[self.current_fiber_index]

        self.current_fiber_spots = self.generate_fiber_spots(fibers)

    def generate_fiber_spots(self, fibers):
        if len(fibers) == 0:
            return np.empty((0,))

        kwargs = {
            'instr': create_hedm_instrument(),
            'eta_ome_maps': self.data,
            'orientation': fibers,
        }
        return _angles_from_orientation(**kwargs)

    def clear_current_fiber_plot(self):
        if hasattr(self, '_current_fiber_lines'):
            self._current_fiber_lines.remove()
            del self._current_fiber_lines

    def update_current_fiber_plot(self):
        self.clear_current_fiber_plot()
        hkl_idx = self.current_hkl_index
        if len(self.current_fiber_spots) <= hkl_idx:
            self.draw()
            return

        current = self.current_fiber_spots[hkl_idx]
        if current.size:
            kwargs = {
                'x': current[:, 0],
                'y': current[:, 1],
                's': 36,
                'c': 'm',
                'marker': '+',
            }
            self._current_fiber_lines = self.ax.scatter(**kwargs)

        self.draw()

    @property
    def current_fiber_orientation(self):
        if len(self.generated_fibers) == 0:
            return np.array([0, 0, 0])

        return self.generated_fibers[self.current_fiber_index]

    @property
    def current_fiber_index(self):
        return self.ui.current_fiber_slider.value()

    def current_fiber_slider_value_changed(self):
        self.update_current_fiber()

    def current_fiber_angle_value_changed(self, v):
        new_slider_index = round(v / self.fiber_step)
        self.ui.current_fiber_slider.setValue(new_slider_index)

        # This usually already happens, but make sure the angle gets
        # updated to its new value (it may need to round to the nearest).
        angle = self.current_fiber_index * self.fiber_step
        self.ui.current_fiber_angle.setValue(angle)

    def add_current_fiber(self):
        to_stack = (self.hand_picked_fibers, self.current_fiber_orientation)
        self.hand_picked_fibers = np.vstack(to_stack)
        self.update_picked_fibers_table()

        self.clear_generated_fibers()

        table = self.ui.picked_fibers_table
        last_row = table.rowCount() - 1
        self.select_fiber_rows([last_row])

    def update_picked_fibers_table(self):
        table = self.ui.picked_fibers_table
        table.clearContents()
        table.setColumnCount(3)
        table.setRowCount(len(self.hand_picked_fibers))
        for i, orientation in enumerate(self.hand_picked_fibers):
            for j in range(3):
                item = QTableWidgetItem(f'{orientation[j]:.4f}')
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(i, j, item)

    @property
    def hand_picked_quaternions(self):
        # We store these as 3D exp maps. Convert and return as quaternions.
        quats = quatOfExpMap(self.hand_picked_fibers.T)
        if quats.ndim == 1:
            # quatOfExpMap() squeezes the output. We must reshape it.
            quats = np.atleast_2d(quats).T

        return quats

    @property
    def hand_picked_fibers(self):
        return self._hand_picked_fibers

    @hand_picked_fibers.setter
    def hand_picked_fibers(self, v):
        self._hand_picked_fibers = v
        # Clear the cache for hand picked spots
        self.cached_hand_picked_spots.clear()

    def clear_selected_fibers_artists(self):
        lines = getattr(self, '_selected_fibers_artists', [])
        while lines:
            lines.pop(0).remove()

    @property
    def selected_fibers_rows(self):
        selected = self.ui.picked_fibers_table.selectionModel().selectedRows()
        selected = [] if None else selected
        return [x.row() for x in selected]

    def picked_fibers_table_selection_changed(self):
        self.draw_selected_fibers()

        enable_delete = len(self.selected_fibers_rows) > 0
        self.ui.picked_fibers_delete_selected.setEnabled(enable_delete)

    def spots_for_hand_picked_quaternion(self, i):
        if i >= len(self.hand_picked_fibers):
            return None

        cache = self.cached_hand_picked_spots

        # Check the cache first. If not present, add to the cache.
        if i not in cache:
            fiber = self.hand_picked_fibers[i]
            if not fiber.size:
                return None

            cache[i] = self.generate_fiber_spots(fiber)

        return cache[i][self.current_hkl_index]

    def draw_selected_fibers(self):
        self.clear_selected_fibers_artists()

        artists = []
        for i in self.selected_fibers_rows:
            spots = self.spots_for_hand_picked_quaternion(i)
            if spots is None or spots.size == 0:
                continue

            kwargs = {
                'x': spots[:, 0],
                'y': spots[:, 1],
                's': 36,
                'marker': 'o',
                'facecolors': 'none',
                'edgecolors': 'c',
                'linewidths': 1,
            }
            artists.append(self.ax.scatter(**kwargs))

        self._selected_fibers_artists = artists
        self.draw()

    def select_fiber_rows(self, rows):
        table = self.ui.picked_fibers_table
        selection_model = table.selectionModel()

        with block_signals(selection_model):
            selection_model.clearSelection()
            command = QItemSelectionModel.Select | QItemSelectionModel.Rows

            for i in rows:
                if i is None or i >= table.rowCount():
                    # Out of range. Don't do anything.
                    continue

                # Select the row
                model_index = selection_model.model().index(i, 0)
                selection_model.select(model_index, command)

        self.picked_fibers_table_selection_changed()

    def delete_selected_fiber_rows(self):
        selected = self.selected_fibers_rows
        self.hand_picked_fibers = np.delete(self.hand_picked_fibers,
                                            selected, 0)
        # There should be no selection now
        self.select_fiber_rows([])
        self.update_picked_fibers_table()

    def synchronize_fiber_step_boxes(self, v):
        self.ui.fiber_step.setValue(v)
        self.ui.hand_picked_fiber_step.setValue(v)

    def fiber_step_value_changed(self, v):
        prev_angle = self.ui.current_fiber_angle.value()

        self.ui.current_fiber_slider.setRange(
            0, self.num_hand_picked_fibers - 1)
        self.ui.current_fiber_angle.setSingleStep(self.fiber_step)

        if self.quaternions_hand_picked:
            # Re-create the generated fibers
            # Restore the closest value to the previous angle
            self.recreate_generated_fibers()
            self.ui.current_fiber_angle.setValue(prev_angle)

    @property
    def fiber_step(self):
        return self.ui.fiber_step.value()

    @fiber_step.setter
    def fiber_step(self, v):
        self.ui.fiber_step.setValue(v)

    @property
    def num_hand_picked_fibers(self):
        return round(360 / self.fiber_step)


class ValidationException(Exception):
    pass
