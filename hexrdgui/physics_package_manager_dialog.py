import copy
import numpy as np

from matplotlib.patches import Rectangle, Polygon
from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import QSizePolicy

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class PhysicsPackageManagerDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('physics_package_manager_dialog.ui', parent)

        canvas = FigureCanvas(Figure(tight_layout=True))
        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.diagram = PhysicsPackageDiagram(canvas)
        self.ui.diagram.addWidget(canvas)

        self.setup_connections()

    def show(self):
        self.setup_form()
        self.ui.show()

    @property
    def material_selectors(self):
        return {
            'sample': self.ui.sample_material,
            'pinhole': self.ui.pinhole_material,
            'window': self.ui.window_material
        }

    @property
    def material_inputs(self):
        return {
            'sample': self.ui.sample_material_input,
            'pinhole': self.ui.pinhole_material_input,
            'window': self.ui.window_material_input
        }

    @property
    def density_inputs(self):
        return {
            'sample': self.ui.sample_density,
            'pinhole': self.ui.pinhole_density,
            'window': self.ui.window_density
        }

    def setup_connections(self):
        self.ui.show_pinhole.toggled.connect(self.toggle_pinhole)
        self.ui.show_window.toggled.connect(self.toggle_window)
        self.ui.button_box.accepted.connect(self.ui.accept)
        self.ui.button_box.rejected.connect(self.ui.reject)
        for k, w in self.material_selectors.items():
            w.currentIndexChanged.connect(
                lambda index, k=k: self.material_changed(index, k))

    def setup_form(self):
        mat_names = list(HexrdConfig().materials.keys())
        options = ['Enter Manually', *mat_names]
        for w in self.material_selectors.values():
            w.clear()
            w.addItems(options)
            w.insertSeparator(1)

    def draw_diagram(self):
        window = self.ui.show_window.isChecked()
        pinhole = self.ui.show_pinhole.isChecked()
        self.diagram.update_diagram(window, pinhole)

    def toggle_window(self, enabled):
        self.ui.window_tab.setEnabled(enabled)
        self.draw_diagram()

    def toggle_pinhole(self, enabled):
        self.ui.pinhole_tab.setEnabled(enabled)
        self.draw_diagram()

    def material_changed(self, index, category):
        material = self.material_selectors[category].currentText()
        self.material_inputs[category].setEnabled(index == 0)
        self.density_inputs[category].setEnabled(index == 0)
        if index > 0:
            material = HexrdConfig().materials[material]
            density = getattr(material.unitcell, 'density', 0)
            self.density_inputs[category].setValue(density)
        else:
            self.density_inputs[category].setValue(0.0)


class PhysicsPackageDiagram:

    offset = 0.20
    patches = {
        'NIF laser drive': Polygon([(0.05, 0.2), (0.05, 0.8), (0.2, 0.75), (0.2, 0.25)], facecolor=(0.5, 0, 1, 0.3)),
        'ablator': Rectangle((0.2, 0.2), 0.07, 0.6, facecolor=(0, 1, 0, 0.5), edgecolor=(0, 0, 0)),
        'heatshield': Rectangle((0.27, 0.2), 0.03, 0.6, facecolor=(1, 1, 1), edgecolor=(0, 0, 0)),
        'pusher': Rectangle((0.3, 0.2), 0.08, 0.6, facecolor=(0.8, 0, 1, 0.4), edgecolor=(0, 0, 0)),
        'sample': Rectangle((0.38, 0.2), 0.03, 0.6, facecolor=(0, 0, 1, 0.4), edgecolor=(0, 0, 0)),
        'VISAR': Polygon([(0.41, 0.4), (0.41, 0.6), (0.91, 0.65), (0.91, 0.35)], facecolor=(1, 0, 0, 0.3)),
        'window': Rectangle((0.4, 0.2), 0.2, 0.6, facecolor=(1, 1, 0, 0.8), edgecolor=(0, 0, 0)),
        'pinhole': Polygon([(0.6, 0.2), (0.6, 0.8), (0.8, 0.8), (0.75, 0.6), (0.6, 0.6), (0.6, 0.4), (0.75, 0.4), (0.75, 0.6), (0.75, 0.4), (0.8, 0.2)], facecolor=(0.5, 0.5, 0.5, 0.6), edgecolor=(0, 0, 0))

    }

    def __init__(self, canvas):
            self.fig = canvas.figure
            self.ax = self.fig.add_subplot()
            self.ax = self.fig.add_subplot(fc=(0, 0, 0))
            self.ax.set_axis_off()
            self.ax.set_aspect(1)
            self.update_diagram()

    def clear(self):
        for text, patch in zip(self.ax.texts, self.ax.patches):
            text.remove()
            patch.remove()

    def add_text(self, patch, label):
        if isinstance(patch, Polygon):
            xy = patch.get_path().vertices
            x = (np.min(xy[:, 0]) + np.max(xy[:, 0])) / 2
            y = (np.min(xy[:, 1]) + np.max(xy[:, 1])) / 2
            if label == 'VISAR':
                # Since this overlaps layers make sure label is not
                # positioned over another layer
                x = (np.min(xy[:, 0]) + np.max(xy[:, 0])) / 1.5
        else:
            x, y = patch.get_center()
        self.ax.text(x, y, label, ha='center', va='center', rotation=90, fontsize='small')

    def update_diagram(self, show_window=True, show_pinhole=True):
        self.clear()
        count = 0
        for key, patch in self.patches.items():
            p = copy.deepcopy(patch)
            if key == 'window' and not show_window:
                continue
            if key == 'pinhole':
                if not show_pinhole:
                    continue
                if not show_window:
                    # Shift the pinhole over since no window is present
                    p.xy[:, 0] -= self.offset
            # Add some spacing between each layer
            if isinstance(p, Polygon):
                p.xy[:, 0] += count * 0.01
            elif isinstance(p, Rectangle):
                p.set_x(p.xy[0] + count * 0.01)
            self.ax.add_patch(p)
            self.add_text(p, key)
            count += 1
        self.fig.canvas.draw_idle()
