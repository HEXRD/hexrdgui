import copy
import h5py
import numpy as np

from matplotlib.patches import Rectangle, Polygon
from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import QSizePolicy

from hexrdgui.create_hedm_instrument import create_hedm_instrument
import hexrdgui.resources.materials as module
from hexrdgui import resource_loader
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.guess_instrument_type import guess_instrument_type

from hexrd.material import _angstroms, _kev, Material


class PhysicsPackageManagerDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('physics_package_manager_dialog.ui', parent)
        self.additional_materials = {}

        canvas = FigureCanvas(Figure(tight_layout=True))
        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.diagram = PhysicsPackageDiagram(canvas)
        self.ui.diagram.addWidget(canvas)

        self.load_additional_materials()
        self.update_instrument_type()
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
        self.ui.button_box.accepted.connect(self.accept_changes)
        self.ui.button_box.accepted.connect(self.ui.accept)
        self.ui.button_box.rejected.connect(self.ui.reject)
        for k, w in self.material_selectors.items():
            w.currentIndexChanged.connect(
                lambda index, k=k: self.material_changed(index, k))
        HexrdConfig().instrument_config_loaded.connect(self.update_instrument_type)

    def load_additional_materials(self):
        # Use a high dmin since we do not care about the HKLs here.
        dmin = _angstroms(2)
        energy = _kev(HexrdConfig().beam_energy)
        for key in ['pinhole', 'window']:
            materials = {}
            file_name = f'{key}_materials.h5'
            with resource_loader.path(module, file_name) as file_path:
                with h5py.File(file_path) as f:
                    mat_names = list(f.keys())

                    for name in mat_names:
                        materials[name] = Material(name, file_path, dmin=dmin,
                                                   kev=energy)
            self.additional_materials[key] = materials

    def update_instrument_type(self):
        instr = create_hedm_instrument()
        self.instrument_type = guess_instrument_type(instr.detectors)
        if self.instrument_type == 'PXRDIP':
            pinhole = HexrdConfig().pinhole_package
            pinhole.thickness = 70
            pinhole.diameter = 130

    def setup_form(self):
        mat_names = list(HexrdConfig().materials.keys())
        for key, w in self.material_selectors.items():
            custom_mats = list(self.additional_materials.get(key, {}))
            options = ['Enter Manually', *custom_mats, *mat_names]
            w.clear()
            w.addItems(options)
            w.insertSeparator(1)
            w.insertSeparator(2 + len(custom_mats))

        # Set default values
        physics = HexrdConfig().physics_package
        pinhole = HexrdConfig().pinhole_package
        # PINHOLE
        self.ui.pinhole_material.setCurrentText(pinhole.material)
        self.ui.pinhole_density.setValue(pinhole.density)
        if self.instrument_type == 'PXRDIP':
            self.ui.pinhole_thickness.setValue(70)
            self.ui.pinhole_diameter.setValue(130)
        else:
            self.ui.pinhole_thickness.setValue(pinhole.thickness)
            self.ui.pinhole_diameter.setValue(pinhole.diameter)
        # WINDOW
        if physics.window_material not in options:
            self.ui.window_material_input.setText(
                physics.window_material)
        else:
            self.ui.window_material.setCurrentText(
                physics.window_material)
        self.ui.window_density.setValue(physics.window_density)
        self.ui.window_thickness.setValue(physics.window_thickness)
        # SAMPLE
        if physics.sample_material not in options:
            self.ui.sample_material_input.setText(
                physics.sample_material)
        else:
            self.ui.sample_material.setCurrentText(
                physics.sample_material)
        self.ui.sample_density.setValue(physics.sample_density)
        self.ui.sample_thickness.setValue(physics.sample_thickness)

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
        if category == 'pinhole':
            self.ui.absorption_length.setEnabled(index == 0)

        if index > 0:
            try:
                material = HexrdConfig().materials[material]
            except KeyError:
                material = self.additional_materials[category][material]
            density = getattr(material.unitcell, 'density', 0)
            self.density_inputs[category].setValue(density)
        else:
            self.density_inputs[category].setValue(0.0)
        energy = HexrdConfig().beam_energy
        absorption_length = HexrdConfig().pinhole_package.absorption_length
        self.ui.absorption_length.setValue(absorption_length(energy))

    def accept_changes(self):
        materials = {}
        for key, selector in self.material_selectors.items():
            if selector.currentIndex() == 0:
                materials[key] = self.material_inputs[key].text()
            else:
                materials[key] = selector.currentText()

        physics_package = {
            'sample_material': materials['sample'],
            'sample_density': self.ui.sample_density.value(),
            'sample_thickness': self.ui.sample_thickness.value(),
            'window_material': materials['window'],
            'window_density': self.ui.window_density.value(),
            'window_thickness': self.ui.window_thickness.value(),
        }
        pinhole = {
            'material': materials['pinhole'],
            'diameter': self.ui.pinhole_diameter.value(),
            'thickness': self.ui.pinhole_thickness.value(),
            'density': self.ui.pinhole_density.value(),
        }
        HexrdConfig().physics_package = physics_package
        HexrdConfig().pinhole_package = pinhole

        if HexrdConfig().apply_absorption_correction:
            # Make sure changes are reflected
            HexrdConfig().deep_rerender_needed.emit()


class PhysicsPackageDiagram:

    offset = 0.20
    patches = {
        'laser drive': Polygon(
            [(0.05, 0.2), (0.05, 0.8), (0.2, 0.75), (0.2, 0.25)],
            facecolor=(0.5, 0, 1, 0.3)),
        'ablator': Rectangle((0.2, 0.2), 0.07, 0.6, facecolor=(0, 1, 0, 0.5),
                             edgecolor=(0, 0, 0)),
        'heatshield': Rectangle((0.27, 0.2), 0.03, 0.6, facecolor=(1, 1, 1),
                                edgecolor=(0, 0, 0)),
        'pusher': Rectangle((0.3, 0.2), 0.08, 0.6, facecolor=(0.8, 0, 1, 0.4),
                            edgecolor=(0, 0, 0)),
        'sample': Rectangle((0.38, 0.2), 0.03, 0.6, facecolor=(0, 0, 1, 0.4),
                            edgecolor=(0, 0, 0)),
        'VISAR': Polygon(
            [(0.41, 0.4), (0.41, 0.6), (0.91, 0.65), (0.91, 0.35)],
            facecolor=(1, 0, 0, 0.3)),
        'window': Rectangle((0.4, 0.2), 0.2, 0.6, facecolor=(1, 1, 0, 0.8),
                            edgecolor=(0, 0, 0)),
        'pinhole': Polygon(
            [(0.6, 0.2), (0.6, 0.8), (0.8, 0.8), (0.75, 0.6), (0.6, 0.6),
             (0.6, 0.4), (0.75, 0.4), (0.75, 0.6), (0.75, 0.4), (0.8, 0.2)],
            facecolor=(0.5, 0.5, 0.5, 0.6), edgecolor=(0, 0, 0))

    }

    def __init__(self, canvas):
        self.fig = canvas.figure
        self.ax = self.fig.add_subplot()
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
        self.ax.text(x, y, label, ha='center', va='center',
                     rotation=90, fontsize='small')

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
