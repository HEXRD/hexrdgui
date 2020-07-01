import copy

import matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np
from scipy import ndimage
import yaml

from PySide2.QtCore import Signal, QObject, QSignalBlocker, Qt
from PySide2.QtWidgets import QComboBox, QFileDialog, QSizePolicy

from hexrd.ui import resource_loader

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader

import hexrd.ui.constants
import hexrd.ui.resources.indexing


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
        self.spots = None

        self.setup_widget_paths()

        self.setup_combo_box_item_data()

        # Hide the method tab bar. The user selects it via the combo box.
        self.ui.tab_widget.tabBar().hide()

        self.setup_plot()
        self.setup_color_map()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.active_hkl.currentIndexChanged.connect(self.clear_spots)
        self.ui.active_hkl.currentIndexChanged.connect(self.update_plot)
        self.ui.label_spots.toggled.connect(self.update_spots)
        self.ui.export_button.pressed.connect(self.on_export_button_pressed)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

        self.ui.method.currentIndexChanged.connect(self.update_method_tab)
        self.color_map_editor.ui.minimum.valueChanged.connect(
            self.update_spots)

    def setup_combo_box_item_data(self):
        # Set the item data for the combo boxes to be the names we want
        item_data = [
            'label',
            'blob_dog',
            'blob_log'
        ]
        for i, data in enumerate(item_data):
            self.ui.method.setItemData(i, data)

        item_data = [
            'dbscan',
            'sph-dbscan',
            'ort-dbscan',
            'fclusterdata'
        ]
        for i, data in enumerate(item_data):
            self.ui.clustering_algorithm.setItemData(i, data)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        # Any validation may be performed here first
        self.update_config()
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

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
    def method_name(self):
        return self.ui.method.currentData()

    @method_name.setter
    def method_name(self, v):
        w = self.ui.method
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unable to set method: {v}')

    def update_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.method_name + '_tab')
        self.ui.tab_widget.setCurrentWidget(method_tab)

    def update_hkl_options(self):
        # This won't trigger a re-draw. Can change in the future if needed.
        hkl_indices = self.data.iHKLList
        all_hkls = self.data.planeData.getHKLs(asStr=True)
        hkls = [all_hkls[i] for i in hkl_indices]

        blocker = QSignalBlocker(self.ui.active_hkl)  # noqa: F841
        self.ui.active_hkl.clear()
        self.ui.active_hkl.addItems(hkls)

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
        fig.canvas.set_window_title('HEXRD')
        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, False)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def setup_color_map(self):
        self.color_map_editor = ColorMapEditor(self, self.ui)
        self.ui.grid_layout.addWidget(self.color_map_editor.ui, 0, 0, -1, 1)
        self.update_cmap_bounds()

        # Set the initial max as 20
        self.color_map_editor.ui.maximum.setValue(20)

    def exec_(self):
        self.update_plot()
        self.ui.exec_()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, d):
        if hasattr(self, '_data') and d == self._data:
            return

        self._data = d
        self.update_extent()
        self.update_cmap_bounds()

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

        self.color_map_editor.update_bounds(self.image_data)

    @property
    def display_spots(self):
        return self.ui.label_spots.isChecked()

    def clear_spots(self):
        self.clear_spot_lines()
        self.spots = None

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
        self._spot_lines = self.ax.scatter(self.spots[:, 1], self.spots[:, 0],
                                           18, 'm', '+')
        self.draw()

    def update_plot(self):
        ax = self.ax

        data = self.image_data
        if isinstance(self.norm, matplotlib.colors.LogNorm):
            # The log norm can't handle NaNs. Set them to -1.
            data = copy.deepcopy(data)
            data[np.isnan(data)] = -1

        if not hasattr(self, 'im'):
            im = ax.imshow(data)
            self.im = im
            self.original_extent = im.get_extent()
        else:
            im = self.im
            im.set_data(data)

        self.update_spots()

        im.set_cmap(self.cmap)
        im.set_norm(self.norm)

        im.set_extent(self.extent)
        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')

        self.draw()

    def draw(self):
        self.fig.canvas.draw()

    @property
    def current_hkl_index(self):
        return self.ui.active_hkl.currentIndex()

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.update_plot()

    def set_norm(self, norm):
        self.norm = norm
        self.update_plot()

    def create_spots(self):
        # Make a deep copy to modify
        data = copy.deepcopy(self.image_data)

        # Get rid of nans to make our work easier
        data[np.isnan(data)] = 0

        structure = np.ones((3, 3))
        labels, numSpots = ndimage.label(data > self.threshold, structure)

        index = np.arange(np.amax(labels)) + 1
        spots = ndimage.measurements.center_of_mass(data, labels, index)
        spots = np.array(spots)

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
            if not selected_file.endswith('.npz'):
                selected_file += '.npz'

            self.data.save(selected_file)

    @property
    def threshold(self):
        return self.color_map_editor.ui.minimum.value()

    @threshold.setter
    def threshold(self, v):
        self.color_map_editor.ui.minimum.setValue(v)

    @property
    def yaml_widgets(self):
        return [getattr(self.ui, x) for x in self.widget_paths.keys()]

    @property
    def all_widgets(self):
        return self.yaml_widgets + [
            self.ui.method,
            self.ui.tab_widget,
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

        config = HexrdConfig().indexing_config

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

        # Update the method name
        method = config['find_orientations']['seed_search']['method']
        self.method_name = next(iter(method))
        self.update_method_tab()

        # Also set the color map minimum to the threshold value...
        self.threshold = config['find_orientations']['threshold']

    def update_config(self):
        # Update all of the config with their settings from the widgets
        config = HexrdConfig().indexing_config

        # Clear the method so it can be set to a different one
        method = config['find_orientations']['seed_search']['method']
        method.clear()

        # Give it some dummy contents so the setter below will run
        method_name = self.method_name
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
        config['find_orientations']['threshold'] = self.threshold
