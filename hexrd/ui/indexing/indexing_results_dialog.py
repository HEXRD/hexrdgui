import copy

from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from PySide2.QtCore import Signal, QObject, Qt, QTimer
from PySide2.QtWidgets import QSizePolicy

from hexrd.transforms import xfcapi

from hexrd.ui.color_map_editor import ColorMapEditor
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.grains_viewer_dialog import GrainsViewerDialog
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals

import hexrd.ui.constants


class IndexingResultsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, ome_maps, grains_table, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('indexing_results_dialog.ui', parent)

        self.ome_maps = ome_maps
        self.grains_table = grains_table
        self.cmap = hexrd.ui.constants.DEFAULT_CMAP
        self.norm = None
        self.transform = lambda x: x

        # Cache the sim results so we only have to compute them once
        self.cached_sim_results = {}

        self.setup_plot()
        self.setup_color_map()
        self.setup_grain_id_options()
        self.setup_hkl_options()
        self.update_enable_states()

        self.setup_connections()

    def setup_connections(self):
        self.ui.view_grains.clicked.connect(self.view_grains)
        self.ui.current_hkl.currentIndexChanged.connect(self.update_plot)
        self.ui.show_results.toggled.connect(self.show_results_toggled)
        self.ui.grain_id.currentIndexChanged.connect(self.update_spots)
        self.ui.show_all_grains.toggled.connect(self.show_all_grains_toggled)

        self.ui.accepted.connect(self.accepted.emit)
        self.ui.rejected.connect(self.rejected.emit)

    def update_enable_states(self):
        show_results = self.ui.show_results.isChecked()
        show_all_grains = self.ui.show_all_grains.isChecked()

        enable_grain_id = show_results and not show_all_grains
        self.ui.grain_id_label.setEnabled(enable_grain_id)
        self.ui.grain_id.setEnabled(enable_grain_id)

        self.ui.show_all_grains.setEnabled(show_results)

    def show_results_toggled(self):
        self.update_enable_states()
        self.update_spots()

    def show_all_grains_toggled(self):
        self.update_enable_states()
        self.update_spots()

    def show(self):
        self.update_plot()
        self.ui.show()

    def show_later(self):
        # In case this was called in a separate thread, post the show() to the
        # event loop. Otherwise, on Mac, the dialog will not move to the front.
        QTimer.singleShot(0, lambda: self.show())

    @property
    def extent(self):
        etas = np.degrees(self.ome_maps.etas)
        omes = np.degrees(self.ome_maps.omegas)
        return (etas[0], etas[-1], omes[-1], omes[0])

    @property
    def hkls(self):
        return self.plane_data.getHKLs(*self.ome_maps.iHKLList, asStr=True)

    @property
    def show_all_grains(self):
        return self.ui.show_all_grains.isChecked()

    @property
    def selected_grain_ids(self):
        # Currently: all or one
        if self.show_all_grains:
            return list(range(len(self.grains_table)))

        return [self.ui.grain_id.currentData()]

    def setup_grain_id_options(self):
        w = self.ui.grain_id
        with block_signals(w):
            w.clear()
            for i in range(len(self.grains_table)):
                display_id = int(self.grains_table[i][0])
                w.addItem(str(display_id), i)

    def setup_hkl_options(self):
        w = self.ui.current_hkl
        with block_signals(w):
            w.clear()
            w.addItems(self.hkls)

    @property
    def show_spots(self):
        return self.ui.show_results.isChecked()

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

    @property
    def scaled_image_data(self):
        return self.transform(self.image_data)

    @property
    def plane_data(self):
        return self.ome_maps.planeData

    @property
    def munged_plane_data(self):
        # This plane data object is a deep copy of the original one that
        # gets its hkls manipulated. We expect the original plane data to
        # not be modified while this dialog is open.
        if not hasattr(self, '_munged_plane_data'):
            self._munged_plane_data = copy.deepcopy(self.plane_data)

        return self._munged_plane_data

    @property
    def image_data(self):
        return self.ome_maps.dataStore[self.current_hkl_index]

    @property
    def ome_period(self):
        return self.ome_maps.omeEdges[0] + np.radians([0, 360])

    @property
    def eta_period(self):
        return self.ome_maps.etaEdges[0] + np.radians([0, 360])

    def draw(self):
        self.canvas.draw()

    @property
    def current_hkl(self):
        return self.ui.current_hkl.currentText()

    @property
    def current_hkl_index(self):
        return self.ui.current_hkl.currentIndex()

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

    def view_grains(self):
        if not hasattr(self, '_grains_viewer_dialog'):
            self._grains_viewer_dialog = GrainsViewerDialog(self.grains_table,
                                                            self.ui)

        self._grains_viewer_dialog.show()

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

        im.set_extent(self.extent)

        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')

        # We have fixed extents, so disable autoscaling.
        ax.autoscale(False)

        self.draw()

    def clear_spot_lines(self):
        if hasattr(self, '_spot_lines'):
            self._spot_lines.remove()
            del self._spot_lines

    def update_spots(self):
        self.clear_spot_lines()
        if not self.show_spots:
            self.draw()
            return

        self.create_spots()
        if self.spots.size:
            kwargs = {
                'x': self.spots[:, 0],
                'y': self.spots[:, 1],
                's': 30,
                'c': 'lime',
                'marker': 'o',
            }
            self._spot_lines = self.ax.scatter(**kwargs)

        self.draw()

    def simulate_rotation_series(self, hkl_str, grain_idx):
        cache_key = (hkl_str, grain_idx)
        if cache_key in self.cached_sim_results:
            return self.cached_sim_results[cache_key]

        instr = create_hedm_instrument()

        plane_data = self.munged_plane_data

        # Put exclusions on everything except the current hkl
        all_hkls = plane_data.getHKLs(asStr=True, allHKLs=True)
        enabled_idx = all_hkls.index(hkl_str)

        exclusions = plane_data.exclusions
        exclusions[:] = True
        exclusions[enabled_idx] = False

        plane_data.exclusions = exclusions

        crystal_params = self.grains_table[grain_idx][3:15]

        kwargs = {
            'plane_data': plane_data,
            'grain_param_list': [crystal_params],
            'ome_period': self.ome_period,
        }
        sim_data = instr.simulate_rotation_series(**kwargs)

        self.cached_sim_results[cache_key] = sim_data
        return sim_data

    def generate_spots_data(self):
        hkl_str = self.current_hkl

        all_angles = []
        for grain_id in self.selected_grain_ids:
            # This will return cached results if they are available
            sim_data = self.simulate_rotation_series(hkl_str, grain_id)

            # Combine angles from all detectors
            for psim in sim_data.values():
                _, _, valid_angs, _, _ = psim
                for angles in valid_angs:
                    all_angles.append(angles[:, 1:])

        output = np.degrees(np.concatenate(all_angles))

        # Fix eta period
        output[:, 0] = xfcapi.mapAngle(
            output[:, 0], np.degrees(self.eta_period), units='degrees'
        )
        return output

    def create_spots(self):
        self.spots = self.generate_spots_data()

    def update_cmap_bounds(self):
        if not hasattr(self, 'color_map_editor'):
            return

        self.color_map_editor.update_bounds(self.scaled_image_data)
