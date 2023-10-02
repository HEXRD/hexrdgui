from PySide2.QtCore import Qt
from PySide2.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from hexrd.instrument import centers_of_edge_vec

from hexrd.ui.indexing.spot_montage import (
    create_labels, extract_hkls_from_spots_data, montage, SPOTS_DATA_MAP
)
from hexrd.ui.navigation_toolbar import NavigationToolbar
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals
from hexrd.ui.utils.dialog import add_help_url


class ViewSpotsDialog:
    def __init__(self, spots, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('view_spots_dialog.ui', parent)

        url = 'hedm/fit_grains/#visualize-spots'
        add_help_url(self.ui.button_box, url)

        self.setup_canvas()

        self.spots = spots
        self.tolerances = None
        self.tth_centers = None
        self.eta_centers = None
        self.intensities = None
        self.update_grain_id_list()
        self.grain_id_index_changed()

        self.setup_connections()

    def setup_connections(self):
        self.ui.grain_id.currentIndexChanged.connect(
            self.grain_id_index_changed)
        self.ui.detector.currentIndexChanged.connect(
            self.detector_index_changed)
        self.ui.hkl.currentIndexChanged.connect(self.hkl_index_changed)
        self.ui.peak_id.currentIndexChanged.connect(self.update_canvas)
        self.ui.show_ome_centers.toggled.connect(self.update_canvas)
        self.ui.show_frame_indices.toggled.connect(self.update_canvas)

    def setup_canvas(self):
        # Create the figure and axes to use
        canvas = FigureCanvas(Figure())

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        ax = fig.add_subplot()
        ax.format_coord = self.format_coord
        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def clear_data(self):
        # Ensure there is no memory leak, since the spots are large.
        # Go ahead and delete the data now.
        self.spots.clear()

    @property
    def tolerances(self):
        return self._tolerances

    @tolerances.setter
    def tolerances(self, d):
        self._tolerances = d

        self.ui.tolerances.clear()
        if d is None:
            return

        order = ['tth', 'eta', 'ome']
        formatting = '5.2f'
        items = [f'{d[x]:{formatting}} {x}' for x in order]
        items[-1] = 'and ' + items[-1]
        text = ', '.join(items)
        self.ui.tolerances.setText(text)

    def format_coord(self, x, y):
        # Format the coordinates to be displayed on the navigation toolbar.
        # The coordinates are displayed when the mouse is moved.
        required_attrs = [
            self.tth_centers,
            self.eta_centers,
            self.intensities,
        ]

        if any(x is None for x in required_attrs):
            return ''

        m, n, _ = self.intensities.shape

        # Move x and y into a single frame's coordinates
        while x > n:
            x -= n

        while y > m:
            y -= m

        tth_range = np.degrees((self.tth_centers[0], self.tth_centers[-1]))
        eta_range = np.degrees((self.eta_centers[0], self.eta_centers[-1]))

        # Rescale x and y to be within the ranges
        x = np.interp(x, (0, n), tth_range)
        y = np.interp(y, (0, m), eta_range)

        float_format = '8.3f'
        delimiter = ',  '
        prefix = '   '

        labels = []
        labels.append(f'2θ = {x:{float_format}}')
        labels.append(f'η = {y:{float_format}}')

        return prefix + delimiter.join(labels)

    def update_grain_id_list(self):
        prev = self.selected_grain_id
        grain_ids = list(self.spots.keys())
        with block_signals(self.ui.grain_id):
            self.ui.grain_id.clear()
            for id in grain_ids:
                self.ui.grain_id.addItem(str(id), id)

            if prev in grain_ids:
                self.ui.grain_id.setCurrentText(str(prev))

        self.ui.grain_id.setEnabled(len(grain_ids) > 1)

    def update_detector_list(self):
        prev = self.selected_detector_key
        grain_id = self.selected_grain_id
        det_keys = list(self.spots[grain_id][1].keys())
        with block_signals(self.ui.detector):
            self.ui.detector.clear()
            self.ui.detector.addItems(det_keys)

            if prev in det_keys:
                self.ui.detector.setCurrentText(prev)

        self.ui.detector.setEnabled(len(det_keys) > 1)

    def update_hkls_list(self):
        prev = self.selected_gvec_id
        grain_id = self.selected_grain_id
        det_key = self.selected_detector_key
        kwargs = {
            'all_spots': self.spots,
            'grain_id': grain_id,
            'detector_key': det_key,
        }
        self.hkl_data = extract_hkls_from_spots_data(**kwargs)
        hkls = {k: v['str'] for k, v in self.hkl_data.items()}
        with block_signals(self.ui.hkl):
            self.ui.hkl.clear()
            for gid, hkl_str in hkls.items():
                self.ui.hkl.addItem(hkl_str, gid)

            if prev in hkls:
                self.ui.hkl.setCurrentText(hkls[prev])

    def update_peak_ids(self):
        peak_ids = self.hkl_data[self.selected_gvec_id]['peak_ids']
        with block_signals(self.ui.peak_id):
            self.ui.peak_id.clear()
            for peak_id in peak_ids:
                self.ui.peak_id.addItem(str(peak_id), peak_id)

        self.ui.peak_id.setEnabled(len(peak_ids) > 1)

    def grain_id_index_changed(self):
        self.update_detector_list()
        self.detector_index_changed()

    def detector_index_changed(self):
        self.update_hkls_list()
        self.hkl_index_changed()

    def hkl_index_changed(self):
        self.update_peak_ids()
        self.update_canvas()

    @property
    def selected_grain_id(self):
        return self.ui.grain_id.currentData()

    @property
    def selected_detector_key(self):
        return self.ui.detector.currentText()

    @property
    def selected_hkl(self):
        return self.ui.hkl.currentText()

    @property
    def selected_gvec_id(self):
        return self.ui.hkl.currentData()

    @property
    def selected_peak_id(self):
        return self.ui.peak_id.currentData()

    @property
    def show_ome_centers(self):
        return self.ui.show_ome_centers.isChecked()

    @property
    def show_frame_indices(self):
        return self.ui.show_frame_indices.isChecked()

    def clear_canvas(self):
        # Since the montage() function is creating everything from
        # scratch, it is faster for now for us to just throw away
        # the whole canvas and start with a new one. This doesn't
        # take that much time to do...
        layout = self.ui.canvas_layout
        layout.removeWidget(self.canvas)
        layout.removeWidget(self.toolbar)

        self.canvas.deleteLater()
        self.canvas = None

        self.toolbar.deleteLater()
        self.toolbar = None

        self.setup_canvas()

    def update_canvas(self):
        self.clear_canvas()

        data_map = SPOTS_DATA_MAP

        grain_id = self.selected_grain_id
        det_key = self.selected_detector_key
        gvec_id = self.selected_gvec_id
        peak_id = self.selected_peak_id

        data = _find_data(self.spots, grain_id, det_key, gvec_id, peak_id)
        if data is None:
            msg = (
                f'Failed to find spot data for {grain_id=}, {det_key=}, '
                f'{gvec_id=}, and {peak_id=}'
            )
            raise Exception(msg)

        tth_centers = centers_of_edge_vec(data[data_map['tth_edges']])
        eta_centers = centers_of_edge_vec(data[data_map['eta_edges']])

        self.tth_centers = tth_centers
        self.eta_centers = eta_centers

        kwargs = {
            'det_key': det_key,
            'tth_crd': tth_centers,
            'eta_crd': eta_centers,
            'peak_id': data[data_map['peak_id']],
            'hkl': data[data_map['hkl']],
        }
        labels = create_labels(**kwargs)

        intensities = np.transpose(
            data[data_map['patch_data']],
            (1, 2, 0)
        )
        self.intensities = intensities

        # make montage
        kwargs = {
            'X': intensities,
            'threshold': 0,
            'fig_ax': (self.fig, self.ax),
            **labels,
        }
        if self.show_ome_centers:
            kwargs['ome_centers'] = np.degrees(data[data_map['ome_eval']])

        if self.show_frame_indices:
            kwargs['frame_indices'] = data[data_map['frame_indices']]

        montage(**kwargs)


def _find_data(all_spots, grain_id, det_key, gvec_id, peak_id):
    data_map = SPOTS_DATA_MAP

    if grain_id not in all_spots:
        return

    spots = all_spots[grain_id]

    if det_key not in spots[1]:
        return

    spot_output = spots[1][det_key]
    for spot_id, data in enumerate(spot_output):
        if data[data_map['hkl_id']] != gvec_id:
            continue

        if data[data_map['peak_id']] != peak_id:
            continue

        return data


if __name__ == '__main__':
    import pickle
    import sys

    from PySide2.QtWidgets import QApplication

    if len(sys.argv) < 2:
        sys.exit('Usage: <script> <spots.pkl>')

    app = QApplication(sys.argv)

    spots_file = sys.argv[1]

    with open(spots_file, 'rb') as rf:
        spots_data = pickle.load(rf)

    dialog = ViewSpotsDialog(spots_data)
    dialog.tolerances = {'tth': 0.25, 'eta': 3.0, 'ome': 2.0}

    dialog.ui.finished.connect(app.quit)
    dialog.ui.show()
    app.exec_()
