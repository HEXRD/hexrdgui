import h5py

from hexrdgui import resource_loader
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
import hexrdgui.resources.materials as module

from hexrd.material import _angstroms, _kev, Material


class AbsorptionCorrectionOptionsDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('absorption_correction_options_dialog.ui',
                                   parent)

        self.additional_materials = {}
        self.filters = {n: {} for n in HexrdConfig().detector_names}
        self.mat_options = []

        self.load_additional_materials()
        self.setup_connections()
        self.update_gui()

    @property
    def material_selectors(self):
        return {
            'filter': self.ui.filter_material,
            'coating': self.ui.coating_material,
            'phosphor': self.ui.phosphor_material
        }

    @property
    def material_inputs(self):
        return {
            'filter': self.ui.filter_material_input,
            'coating': self.ui.coating_material_input,
            'phosphor': self.ui.phosphor_material_input
        }

    @property
    def density_inputs(self):
        return {
            'filter': self.ui.filter_density,
            'coating': self.ui.coating_density,
            'phosphor': self.ui.phosphor_density
        }

    def load_additional_materials(self):
        # FIXME: Update to use defaults once they've been added to HEXRD
        return

    def update_gui(self):
        # Filter info is set per detector
        self.ui.detectors.addItems(HexrdConfig().detector_names)

        # In addition to loaded materials include other useful materials
        # for each layer
        mat_names = list(HexrdConfig().materials.keys())
        for key, w in self.material_selectors.items():
            custom_mats = list(self.additional_materials.get(key, {}))
            self.mat_options = ['Enter Manually', *custom_mats, *mat_names]
            w.clear()
            w.addItems(self.mat_options)
            w.insertSeparator(1)
            w.insertSeparator(2 + len(custom_mats))

        # Set default values
        filter = HexrdConfig().detector_filter(self.ui.detectors.currentText())
        coating = HexrdConfig().detector_coating
        phosphor = HexrdConfig().phosphor
        # FILTER
        if filter.material not in self.mat_options:
            self.ui.filter_material_input.setText(filter.material)
        else:
            self.ui.filter_material.setCurrentText(filter.material)
        self.ui.filter_density.setValue(filter.density)
        self.ui.filter_thickness.setValue(filter.thickness)
        # COATING
        if coating.material not in self.mat_options:
            self.ui.coating_material_input.setText(coating.material)
        else:
            self.ui.coating_material.setCurrentText(coating.material)
        self.ui.coating_density.setValue(coating.density)
        self.ui.coating_thickness.setValue(coating.thickness)
        # PHOSPHOR
        if phosphor.material not in self.mat_options:
            self.ui.phosphor_material_input.setText(phosphor.material)
        else:
            self.ui.phosphor_material.setCurrentText(phosphor.material)
        self.ui.phosphor_density.setValue(phosphor.density)
        self.ui.phosphor_thickness.setValue(phosphor.thickness)
        self.ui.phosphor_readout_length.setValue(phosphor.readout_length)
        self.ui.phosphor_pre_U0.setValue(phosphor.pre_U0)

    def setup_connections(self):
        for k, w in self.material_selectors.items():
            w.currentIndexChanged.connect(
                lambda index, k=k: self.material_changed(index, k))
        self.ui.filter_density.valueChanged.connect(self.filter_info_changed)
        self.ui.filter_thickness.valueChanged.connect(self.filter_info_changed)
        self.ui.detectors.currentTextChanged.connect(self.detector_changed)
        self.ui.button_box.accepted.connect(self.accept_changes)
        self.ui.button_box.accepted.connect(self.ui.accept)
        self.ui.button_box.rejected.connect(self.ui.reject)

    def exec(self):
        return self.ui.exec()

    def material_changed(self, index, category):
        selected = self.material_selectors[category].currentText()
        self.material_inputs[category].setEnabled(index == 0)
        self.density_inputs[category].setEnabled(index == 0)

        if index > 0:
            self.material_inputs[category].setText('')
            try:
                material = HexrdConfig().materials[selected]
            except KeyError:
                material = self.additional_materials[category][selected]
            density = getattr(material.unitcell, 'density', 0)
            self.density_inputs[category].setValue(density)
            if category == 'filter':
                det_name = self.ui.detectors.currentText()
                self.filters.setdefault(det_name, {})
                self.filters[det_name]['material'] = material
        else:
            self.density_inputs[category].setValue(0.0)

    def filter_info_changed(self):
        det_name = self.ui.detectors.currentText()
        self.filters.setdefault(det_name, {})
        self.filters[det_name]['density'] = self.ui.filter_density.value()
        self.filters[det_name]['thickness'] = self.ui.filter_thickness.value()

    def detector_changed(self, new_det):
        filter = HexrdConfig().detector_filter(new_det)
        mat = self.filters[new_det].get('material', filter.material)
        if filter.material not in self.mat_options:
            self.ui.filter_material_input.setText(mat)
        else:
            self.ui.filter_material.setCurrentText(mat)
        density = self.filters[new_det].get('density', filter.density)
        self.ui.filter_density.setValue(density)
        thickness = self.filters[new_det].get('thickness', filter.thickness)
        self.ui.filter_thickness.setValue(thickness)

    def accept_changes(self):
        materials = {}
        for key, selector in self.material_selectors.items():
            if selector.currentIndex() == 0:
                materials[key] = self.material_inputs[key].text()
            else:
                materials[key] = selector.currentText()

        for det_name in HexrdConfig().detector_names:
            HexrdConfig().update_detector_filter(
                det_name, **self.filters[det_name])

        HexrdConfig().detector_coating = {
            'material': materials['coating'],
            'density': self.ui.coating_density.value(),
            'thickness': self.ui.coating_thickness.value()
        }
        HexrdConfig().phosphor = {
            'material': materials['phosphor'],
            'density': self.ui.phosphor_density.value(),
            'thickness': self.ui.phosphor_thickness.value()
        }
