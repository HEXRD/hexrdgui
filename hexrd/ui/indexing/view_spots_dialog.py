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


class ViewSpotsDialog:
    def __init__(self, spots, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('view_spots_dialog.ui', parent)

        self.setup_canvas()

        self.spots = spots
        self.tolerances = None
        self.update_detector_list()
        self.detector_index_changed()

        self.setup_connections()

    def setup_connections(self):
        self.ui.detector.currentIndexChanged.connect(
            self.detector_index_changed)
        self.ui.hkl.currentIndexChanged.connect(self.hkl_index_changed)
        self.ui.peak_id.currentIndexChanged.connect(self.update_canvas)

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
        float_format = '8.3f'
        delimiter = ',  '
        prefix = '   '

        labels = []
        labels.append(f'eta = {x:{float_format}}')
        labels.append(f'omega = {y:{float_format}}')

        return prefix + delimiter.join(labels)

    def detector_index_changed(self):
        self.update_hkls_list()
        self.hkl_index_changed()

    def hkl_index_changed(self):
        self.update_peak_ids()
        self.update_canvas()

    def update_detector_list(self):
        det_keys = list(self.spots[0][1].keys())
        with block_signals(self.ui.detector):
            self.ui.detector.clear()
            self.ui.detector.addItems(det_keys)

        self.ui.detector.setEnabled(len(det_keys) > 1)

    def update_hkls_list(self):
        det_key = self.selected_detector_key
        self.hkl_data = extract_hkls_from_spots_data(self.spots, det_key)
        hkls = {k: v['str'] for k, v in self.hkl_data.items()}
        with block_signals(self.ui.hkl):
            self.ui.hkl.clear()
            for gid, hkl_str in hkls.items():
                self.ui.hkl.addItem(hkl_str, gid)

    def update_peak_ids(self):
        peak_ids = self.hkl_data[self.selected_gvec_id]['peak_ids']
        with block_signals(self.ui.peak_id):
            self.ui.peak_id.clear()
            for peak_id in peak_ids:
                self.ui.peak_id.addItem(str(peak_id), peak_id)

        self.ui.peak_id.setEnabled(len(peak_ids) > 1)

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

        detector_key = self.selected_detector_key
        gvec_id = self.selected_gvec_id
        peak_id = self.selected_peak_id
        found = False

        for grain_id, spots in self.spots.items():
            for det_key, spot_output in spots[1].items():
                if det_key != detector_key:
                    continue

                for spot_id, data in enumerate(spot_output):
                    if data[data_map['hkl_id']] != gvec_id:
                        continue

                    if data[data_map['peak_id']] != peak_id:
                        continue

                    found = True
                    break

        if not found:
            msg = (
                f'Failed to find spot data for {detector_key=}, {gvec_id=}, '
                f'and {peak_id=}'
            )
            raise Exception(msg)

        tth_edges = data[data_map['tth_edges']]
        eta_edges = data[data_map['eta_edges']]

        kwargs = {
            'det_key': det_key,
            'tth_crd': centers_of_edge_vec(tth_edges),
            'eta_crd': centers_of_edge_vec(eta_edges),
            'peak_id': data[data_map['peak_id']],
            'hkl': data[data_map['hkl']],
        }
        labels = create_labels(**kwargs)

        intensities = np.transpose(
            data[data_map['patch_data']],
            (1, 2, 0)
        )

        # make montage
        kwargs = {
            'X': intensities,
            'threshold': 0,
            'fig_ax': (self.fig, self.ax),
            **labels,
        }
        montage(**kwargs)


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

    dialog.ui.resize(1200, 800)
    dialog.ui.finished.connect(app.quit)
    dialog.ui.show()
    app.exec_()
