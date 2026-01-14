from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy

from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.matplotlib import remove_artist


DEFAULT_STYLE = 'rx'
DEFAULT_LABEL = ''


class HEDMCalibrationResultsDialog:
    def __init__(
        self, data, styles, labels, grain_ids, cfg, title, ome_period, parent=None
    ):
        loader = UiLoader()
        self.ui = loader.load_file('hedm_calibration_results_dialog.ui', parent)

        if isinstance(grain_ids, np.ndarray):
            # So we can easily use the .index() function...
            grain_ids = grain_ids.tolist()

        self.data = data
        self.styles = styles
        self.labels = labels
        self.grain_ids = grain_ids
        self.cfg = cfg
        self.title = title
        self.ome_period = ome_period

        self.setup_combo_boxes()
        self.setup_canvas()
        self.update_canvas()
        self.setup_connections()

    def setup_connections(self):
        self.ui.detector.currentIndexChanged.connect(self.update_canvas)
        self.ui.show_all_grains.toggled.connect(self.show_all_grains_toggled)
        self.ui.grain_id.currentIndexChanged.connect(self.update_canvas)
        self.ui.show_legend.toggled.connect(self.update_canvas)

    def setup_combo_boxes(self):
        self.ui.grain_id.clear()
        for grain_id in sorted(self.grain_ids):
            self.ui.grain_id.addItem(str(grain_id), grain_id)

        self.ui.detector.clear()
        for det_key in self.cfg.instrument.hedm.detectors:
            self.ui.detector.addItem(det_key)

        self.update_enable_states()

    def update_enable_states(self):
        enable_grain_id = not self.show_all_grains and self.ui.grain_id.count() > 1
        self.ui.grain_id.setEnabled(enable_grain_id)
        self.ui.grain_id_label.setEnabled(enable_grain_id)

        enable_detector = self.ui.detector.count() > 1
        self.ui.detector.setEnabled(enable_detector)
        self.ui.detector_label.setEnabled(enable_detector)

        show_all_grains_visible = self.ui.grain_id.count() > 1
        self.ui.show_all_grains.setVisible(show_all_grains_visible)

    def setup_canvas(self):
        self.artists = []

        # Create the figure and axes to use
        canvas = FigureCanvas(Figure())

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        fig = canvas.figure
        fig.suptitle(self.title)
        ax = fig.subplots(1, 2, sharex=True, sharey=False)
        self.ui.canvas_layout.addWidget(canvas)

        ax[0].grid(True)
        ax[0].axis('equal')
        ax[0].set_xlabel('detector X [mm]')
        ax[0].set_ylabel('detector Y [mm]')

        ax[1].grid(True)
        ax[1].set_xlabel('detector X [mm]')
        ax[1].set_ylabel(r'$\omega$ [deg]')

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        self.fig = fig
        self.ax = ax
        self.canvas = canvas

    def exec(self):
        return self.ui.exec()

    @property
    def selected_detector_key(self):
        return self.ui.detector.currentText()

    @property
    def selected_grain_id(self):
        return self.ui.grain_id.currentData()

    @property
    def show_all_grains(self):
        return self.ui.show_all_grains.isChecked()

    @property
    def show_legend(self):
        return self.ui.show_legend.isChecked()

    def show_all_grains_toggled(self):
        self.update_enable_states()
        self.update_canvas()

    @property
    def grain_ids_to_plot(self):
        if self.show_all_grains:
            return self.grain_ids

        return [self.selected_grain_id]

    def clear_artists(self):
        while self.artists:
            remove_artist(self.artists.pop(0))

    def update_canvas(self):
        self.clear_artists()

        instr = self.cfg.instrument.hedm
        ome_period = self.ome_period

        grain_ids = self.grain_ids_to_plot
        det_key = self.selected_detector_key
        panel = instr.detectors[det_key]
        ax = self.ax

        ax[0].set_xlim(-0.5 * panel.col_dim, 0.5 * panel.col_dim)
        ax[0].set_ylim(-0.5 * panel.row_dim, 0.5 * panel.row_dim)

        ax[1].set_xlim(-0.5 * panel.col_dim, 0.5 * panel.col_dim)
        ax[1].set_ylim(ome_period[0], ome_period[1])

        grains_to_plot = [self.grain_ids.index(x) for x in grain_ids]
        for key, data in self.data.items():
            style = self.styles.get(key, DEFAULT_STYLE)
            label = self.labels.get(key, DEFAULT_LABEL)
            self.draw_entry(grains_to_plot, data[det_key], style, label)

        self.canvas.draw()

    def draw_entry(self, indices, data, style, label):
        for i, idx in enumerate(indices):
            x = data[idx][:, 0]
            y1 = data[idx][:, 1]
            y2 = np.degrees(data[idx][:, 2])

            # Only add the label for the first index
            if i != 0:
                label = None

            (artist1,) = self.ax[0].plot(x, y1, style, label=label)
            (artist2,) = self.ax[1].plot(x, y2, style, label=label)

            self.artists.extend([artist1, artist2])

            if self.show_legend:
                legend_kwargs = {
                    'loc': 'lower right',
                    'title': 'Legend',
                }
                artist3 = self.ax[0].legend(**legend_kwargs)
                artist4 = self.ax[1].legend(**legend_kwargs)
                self.artists.extend([artist3, artist4])
