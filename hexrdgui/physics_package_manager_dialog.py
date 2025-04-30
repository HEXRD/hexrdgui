import copy
import h5py
import numpy as np

from matplotlib.patches import Rectangle, Polygon
from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import QSizePolicy, QWidget

from hexrdgui import resource_loader
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.guess_instrument_type import guess_instrument_type

import hexrd.resources as hexrd_resources
from hexrd.material import _angstroms, _kev, Material
from hexrd.instrument.constants import FILTER_DEFAULTS, PINHOLE_DEFAULTS


class PhysicsPackageManagerDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('physics_package_manager_dialog.ui', parent)
        self.additional_materials = {}
        self.instrument_type = None
        self.delete_if_canceled = False

        canvas = FigureCanvas(Figure(tight_layout=True))
        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.diagram = PhysicsPackageDiagram(canvas)
        self.ui.diagram.addWidget(canvas)

        self.load_additional_materials()
        self.update_instrument_type()
        self.setup_connections()

    def show(self, delete_if_canceled=False):
        self.delete_if_canceled = delete_if_canceled
        self.setup_form()
        self.draw_diagram()
        self.ui.show()

    @property
    def layer_names(self) -> list[str]:
        return self.non_sample_layer_names + ['sample']

    @property
    def non_sample_layer_names(self) -> list[str]:
        # All layer names excluding the sample
        return [
            'ablator',
            'heatshield',
            'pusher',
            'window',
            'pinhole',
        ]

    @property
    def material_selectors(self) -> dict[str, QWidget]:
        return {
            k: getattr(self.ui, f'{k}_material')
            for k in self.layer_names
        }

    @property
    def material_inputs(self) -> dict[str, QWidget]:
        return {
            k: getattr(self.ui, f'{k}_material_input')
            for k in self.layer_names
        }

    @property
    def density_inputs(self):
        return {
            k: getattr(self.ui, f'{k}_density')
            for k in self.layer_names
        }

    def setup_connections(self):
        for k in self.non_sample_layer_names:
            w = getattr(self.ui, f'show_{k}')
            w.toggled.connect(lambda b, k=k: self.toggle_layer(b, k))

        self.ui.button_box.accepted.connect(self.accept_changes)
        self.ui.button_box.accepted.connect(self.ui.accept)
        self.ui.button_box.rejected.connect(self.ui.reject)
        for k, w in self.material_selectors.items():
            w.currentIndexChanged.connect(
                lambda index, k=k: self.material_changed(index, k))
        HexrdConfig().instrument_config_loaded.connect(
            self.update_instrument_type)
        HexrdConfig().detectors_changed.connect(
            self.initialize_detector_coatings)

        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def on_accepted(self):
        self.delete_if_canceled = False

    def on_rejected(self):
        if self.delete_if_canceled:
            HexrdConfig().physics_package = None

        self.delete_if_canceled = False

    def initialize_detector_coatings(self):
        # Reset detector coatings to make sure they're in sync w/ current dets
        HexrdConfig().detector_coatings_dictified = {}
        for det in HexrdConfig().detector_names:
            HexrdConfig().update_detector_filter(det)
            HexrdConfig().update_detector_coating(det)
            HexrdConfig().update_detector_phosphor(det)

    def load_additional_materials(self):
        # Use a high dmin since we do not care about the HKLs here.
        dmin = _angstroms(2)
        energy = _kev(HexrdConfig().beam_energy)
        for key in ['pinhole', 'window']:
            materials = {}
            file_name = f'{key}_materials.h5'
            with resource_loader.path(hexrd_resources, file_name) as file_path:
                with h5py.File(file_path) as f:
                    mat_names = list(f.keys())

                    for name in mat_names:
                        materials[name] = Material(name, file_path, dmin=dmin,
                                                   kev=energy)
            self.additional_materials[key] = materials

    def update_instrument_type(self):
        new_instr_type = guess_instrument_type(HexrdConfig().detector_names)
        if new_instr_type == self.instrument_type:
            return

        self.initialize_detector_coatings()
        if new_instr_type == 'TARDIS':
            HexrdConfig().update_physics_package(**PINHOLE_DEFAULTS.TARDIS)
            for det in HexrdConfig().detector_names:
                HexrdConfig().update_detector_filter(
                    det, **FILTER_DEFAULTS.TARDIS)
        elif new_instr_type == 'PXRDIP':
            HexrdConfig().update_physics_package(**PINHOLE_DEFAULTS.PXRDIP)
            for det in HexrdConfig().detector_names:
                HexrdConfig().update_detector_filter(
                    det, **FILTER_DEFAULTS.PXRDIP)
        else:
            HexrdConfig().create_default_physics_package()
        self.instrument_type = new_instr_type

    def setup_form(self):
        mat_names = list(HexrdConfig().materials.keys())
        all_options = {}
        for key, w in self.material_selectors.items():
            custom_mats = list(self.additional_materials.get(key, {}))
            options = ['Enter Manually', *custom_mats, *mat_names]
            all_options[key] = options
            w.clear()
            w.addItems(options)
            w.insertSeparator(1)
            w.insertSeparator(2 + len(custom_mats))

        # Set default values
        if not HexrdConfig().has_physics_package:
            return

        physics = HexrdConfig().physics_package
        # PINHOLE
        self.ui.pinhole_material.setCurrentText(physics.pinhole_material)
        self.ui.pinhole_density.setValue(physics.pinhole_density)
        if self.instrument_type == 'PXRDIP':
            self.ui.pinhole_thickness.setValue(70)
            self.ui.pinhole_diameter.setValue(300)
        else:
            self.ui.pinhole_thickness.setValue(physics.pinhole_thickness)
            self.ui.pinhole_diameter.setValue(physics.pinhole_diameter)

        # THE REST
        layer_names = self.layer_names
        # Remove pinhole, cause we did that manually
        layer_names.remove('pinhole')

        material_selectors = self.material_selectors
        material_inputs = self.material_inputs
        for name in layer_names:
            material = getattr(physics, f'{name}_material')
            if material not in all_options[name]:
                w = material_inputs[name]
                w.setText(material)
            else:
                w = material_selectors[name]
                w.setCurrentText(material)

            for key in ('density', 'thickness'):
                attr = f'{name}_{key}'
                w = getattr(self.ui, attr)
                w.setValue(getattr(physics, attr))

        self.update_layer_enable_states()

    def draw_diagram(self):
        show_dict = {
            k: getattr(self.ui, f'show_{k}').isChecked()
            for k in self.non_sample_layer_names
        }
        self.diagram.update_diagram(show_dict)

    def toggle_layer(self, enabled: bool, name: str):
        w = getattr(self.ui, f'{name}_tab')
        w.setEnabled(enabled)
        self.draw_diagram()

    def update_layer_enable_states(self):
        for name in self.non_sample_layer_names:
            enable = self.layer_thickness(name) != 0.0
            self.set_layer_enabled(name, enable)

    def set_layer_enabled(self, name: str, enable: bool):
        w = getattr(self.ui, f'show_{name}')
        w.setChecked(enable)

    def layer_enabled(self, name: str) -> bool:
        w = getattr(self.ui, f'{name}_tab')
        return w.isEnabled()

    def layer_thickness(self, name: str) -> float:
        if not self.layer_enabled(name):
            return 0.0

        w = getattr(self.ui, f'{name}_thickness')
        return w.value()

    def material_changed(self, index, category):
        material = self.material_selectors[category].currentText()

        self.material_inputs[category].setEnabled(index == 0)
        self.density_inputs[category].setEnabled(index == 0)
        if category == 'pinhole':
            self.ui.absorption_length.setEnabled(index == 0)

        if index > 0:
            self.material_inputs[category].setText('')
            try:
                material = HexrdConfig().materials[material]
            except KeyError:
                material = self.additional_materials[category][material]
            density = getattr(material.unitcell, 'density', 0)
            self.density_inputs[category].setValue(density)
        else:
            self.density_inputs[category].setValue(0.0)

        if HexrdConfig().has_physics_package:
            self.ui.absorption_length.setValue(
                HexrdConfig().absorption_length())

    def accept_changes(self):
        materials = {}
        for key, selector in self.material_selectors.items():
            if selector.currentIndex() == 0:
                materials[key] = self.material_inputs[key].text()
            else:
                materials[key] = selector.currentText()

        kwargs = {
            'pinhole_diameter': self.ui.pinhole_diameter.value(),
        }
        for name in self.layer_names:
            kwargs[f'{name}_material'] = materials[name]
            for key in ('density', 'thickness'):
                attr = f'{name}_{key}'
                kwargs[attr] = getattr(self.ui, attr).value()

        HexrdConfig().update_physics_package(**kwargs)

        if HexrdConfig().apply_absorption_correction:
            # Make sure changes are reflected
            HexrdConfig().deep_rerender_needed.emit()


class PhysicsPackageDiagram:

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

    def update_diagram(self, show_dict: dict[str, bool]):
        self.clear()
        count = 0
        offset = 0
        for key, patch in self.patches.items():
            p = copy.deepcopy(patch)
            if not show_dict.get(key, True):
                # Compute width of the patch and adjust the offset
                if isinstance(p, Polygon):
                    xy = p.get_xy()
                    width = xy[:, 0].max() - xy[:, 0].min()
                else:
                    width = p.get_width()

                offset -= width
                continue

            # Apply offset, and add some spacing between each layer
            if isinstance(p, Polygon):
                p.xy[:, 0] += (offset + count * 0.01)
            elif isinstance(p, Rectangle):
                p.set_x(p.xy[0] + offset + count * 0.01)

            self.ax.add_patch(p)
            self.add_text(p, key)
            count += 1
        self.fig.canvas.draw_idle()
