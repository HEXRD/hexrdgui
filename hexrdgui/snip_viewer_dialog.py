from pathlib import Path

import h5py
from matplotlib.backends.backend_qt5agg import FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QSizePolicy

from hexrdgui.color_map_editor import ColorMapEditor
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader


class SnipViewerDialog:
    def __init__(self, data, extent, parent=None):
        self.ui = UiLoader().load_file('snip_viewer_dialog.ui', parent)

        self.data = data
        self.extent = extent

        self.cmap = HexrdConfig().default_cmap
        self.norm = None
        self.transform = lambda x: x

        self.setup_canvas()
        self.setup_color_map()
        self.setup_connections()

    def setup_connections(self):
        self.ui.export_data.clicked.connect(self.export)

    def setup_color_map(self):
        self.color_map_editor = ColorMapEditor(self, self.ui)
        self.ui.color_map_editor_layout.addWidget(self.color_map_editor.ui)
        self.color_map_editor.update_bounds(self.scaled_image_data)

    def setup_canvas(self):
        canvas = FigureCanvas(Figure(tight_layout=True))
        figure = canvas.figure
        ax = figure.add_subplot()

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        ax.set_xlabel(r'2$\theta$ (deg)')
        ax.set_ylabel(r'$\eta$ (deg)')

        algorithm = HexrdConfig().polar_snip1d_algorithm
        titles = ['Fast SNIP 1D', 'SNIP 1D', 'SNIP 2D']
        if algorithm < len(titles):
            title = titles[algorithm]
        else:
            title = f'Algorithm {algorithm}'
        ax.set_title(title)

        im = ax.imshow(self.scaled_image_data, cmap=self.cmap, norm=self.norm)

        ax.relim()
        ax.autoscale_view()
        ax.axis('auto')
        figure.tight_layout()

        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignCenter)

        self.figure = figure
        self.ax = ax
        self.canvas = canvas
        self.im = im

        self.draw_later()

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.im.set_cmap(cmap)
        self.draw_later()

    def set_norm(self, norm):
        self.norm = norm
        self.im.set_norm(norm)
        self.draw_later()

    def set_scaling(self, transform):
        self.transform = transform
        self.im.set_data(self.scaled_image_data)
        self.draw_later()

    @property
    def scaled_image_data(self):
        return self.transform(self.data)

    def show(self):
        self.ui.show()

    def draw_later(self):
        self.figure.canvas.draw_idle()

    def export(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Snip Background', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5);; NPZ files (*.npz)')

        if not selected_file:
            return

        HexrdConfig().working_dir = str(Path(selected_file).parent)
        self.write_data(selected_file)

    def write_data(self, filename):
        filename = Path(filename)

        # Prepare the data to write out
        data = {
            'snip_background': self.data,
            'extent': self.extent,
        }

        # Delete the file if it already exists
        if filename.exists():
            filename.unlink()

        # Check the file extension
        if filename.suffix.lower() == '.npz':
            # If it looks like npz, save as npz
            np.savez(filename, **data)
        else:
            # Default to HDF5 format
            with h5py.File(filename, 'w') as f:
                for key, value in data.items():
                    f.create_dataset(key, data=value)
