import copy
import numpy as np
from numpy.linalg import LinAlgError, inv

from hexrd.material.unitcell import _StiffnessDict

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.matrix_editor import MatrixEditor
from hexrdgui.pressure_slider_dialog import PressureSliderDialog
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import apply_symmetric_constraint, block_signals, compose


class MaterialPropertiesEditor:

    elastic_tensor_shape = (6, 6)

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('material_properties_editor.ui', parent)

        self.null_tensor = np.zeros(self.elastic_tensor_shape)
        self.elastic_tensor_editor = MatrixEditor(self.null_tensor, self.ui)
        self.ui.elastic_tensor_editor_layout.addWidget(
            self.elastic_tensor_editor)

        self.setup_connections()

        self.elastic_tensor_type_changed()

        self.update_gui()

    def setup_connections(self):
        self.ui.elastic_tensor_type.currentIndexChanged.connect(
            self.elastic_tensor_type_changed)
        self.elastic_tensor_editor.data_modified.connect(
            self.elastic_tensor_edited)
        self.ui.show_pressure_slider.clicked.connect(self.show_pressure_slider)

    @property
    def material(self):
        return HexrdConfig().active_material

    @property
    def elastic_tensor_type(self):
        type_map = {
            'Stiffness (GPa)': 'stiffness',
            'Compliance (TPa⁻¹)': 'compliance',
        }
        return type_map[self.ui.elastic_tensor_type.currentText()]

    @property
    def elastic_tensor(self):
        return getattr(self.material.unitcell, self.elastic_tensor_type, None)

    @elastic_tensor.setter
    def elastic_tensor(self, v):
        return setattr(self.material.unitcell, self.elastic_tensor_type, v)

    def elastic_tensor_type_changed(self):
        self.update_elastic_tensor_gui()
        self.update_elastic_tensor_tooltip()

    def update_elastic_tensor_tooltip(self):
        units_map = {
            'stiffness': 'GPa',
            'compliance': 'TPa⁻¹',
        }

        tensor_type = self.elastic_tensor_type
        units = units_map[tensor_type]
        tooltip = (f'The elastic {tensor_type} tensor in Voigt notation. '
                   f'({units})')

        self.ui.elastic_tensor_group.setToolTip(tooltip)

    def update_gui(self):
        self.update_elastic_tensor_gui()
        self.update_misc_gui()

    def update_elastic_tensor_gui(self):
        if (elastic_tensor := self.elastic_tensor) is not None:
            data = copy.deepcopy(elastic_tensor)
        else:
            # Just use zeros...
            data = np.zeros(self.elastic_tensor_shape)

        material = self.material
        enabled, constraints = _StiffnessDict[material.unitcell._laueGroup]

        constraints_func = compose(apply_symmetric_constraint, constraints)

        editor = self.elastic_tensor_editor
        editor.enabled_elements = enabled
        editor.apply_constraints_func = constraints_func
        editor.data = data

    def update_misc_gui(self):
        with block_signals(*self.misc_widgets):
            material = self.material

            density = getattr(material.unitcell, 'density', 0)
            volume = getattr(material, 'vol', 0)
            volume_per_atom = getattr(material, 'vol_per_atom', 0)

            self.ui.density.setValue(density)
            self.ui.volume.setValue(volume)
            self.ui.volume_per_atom.setValue(volume_per_atom)

    def update_enable_states(self):
        matrix_valid = not self.elastic_tensor_editor.matrix_invalid
        self.ui.elastic_tensor_type.setEnabled(matrix_valid)

    def elastic_tensor_edited(self):
        data = copy.deepcopy(self.elastic_tensor_editor.data)
        try:
            self.elastic_tensor = copy.deepcopy(data)
            if self.elastic_tensor_type == 'stiffness':
                # Make sure we can invert it
                inv(self.elastic_tensor)
        except LinAlgError as e:
            self.elastic_tensor_editor.set_matrix_invalid(str(e))
        else:
            self.elastic_tensor_editor.set_matrix_valid()
        self.update_enable_states()

    @property
    def misc_widgets(self):
        return [
            self.ui.density,
            self.ui.volume,
            self.ui.volume_per_atom,
        ]

    def show_pressure_slider(self):
        if dialog := getattr(self, '_pressure_slider_dialog', None):
            dialog.hide()

        dialog = PressureSliderDialog(self.material, self.ui)
        dialog.show()
        self._pressure_slider_dialog = dialog
