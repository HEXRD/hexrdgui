from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals




class AbsorptionCorrectionOptionsDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('absorption_correction_options_dialog.ui',
                                   parent)

        self.additional_materials = {}
        self.mat_options = []

        self.get_initial_filter_values()
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

    @property
    def any_detector_filters_applied(self):
        det_names = HexrdConfig().detector_names
        all_filters = [HexrdConfig().detector_filter(det) for det in det_names]
        return any(filter.thickness > 0 for filter in all_filters)

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
        det = self.ui.detectors.currentText()
        if (filter := HexrdConfig().detector_filter(det)) is None:
            HexrdConfig().update_detector_filter(det)
            filter = HexrdConfig().detector_filter(det)
        if (coating := HexrdConfig().detector_coating(det)) is None:
            HexrdConfig().update_detector_coating(det)
            coating = HexrdConfig().detector_coating(det)
        if (phosphor := HexrdConfig().detector_phosphor(det)) is None:
            HexrdConfig().update_detector_phosphor(det)
            phosphor = HexrdConfig().detector_phosphor(det)

        # FILTER
        if filter.material not in self.mat_options:
            self.ui.filter_material_input.setText(filter.material)
        else:
            self.ui.filter_material.setCurrentText(filter.material)
        self.ui.filter_density.setValue(filter.density)
        self.ui.filter_thickness.setValue(filter.thickness)
        self.ui.apply_filters.setChecked(self.any_detector_filters_applied)
        # COATING
        if coating.material not in self.mat_options:
            self.ui.coating_material_input.setText(coating.material)
        else:
            self.ui.coating_material.setCurrentText(coating.material)
        self.ui.coating_density.setValue(coating.density)
        self.ui.coating_thickness.setValue(coating.thickness)
        self.ui.apply_coating.setChecked(coating.thickness > 0)
        # PHOSPHOR
        if phosphor.material not in self.mat_options:
            self.ui.phosphor_material_input.setText(phosphor.material)
        else:
            self.ui.phosphor_material.setCurrentText(phosphor.material)
        self.ui.phosphor_density.setValue(phosphor.density)
        self.ui.phosphor_thickness.setValue(phosphor.thickness)
        self.ui.apply_phosphor.setChecked(phosphor.thickness > 0)
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
        self.ui.apply_filters.toggled.connect(self.toggle_apply_filters)
        self.ui.apply_coating.toggled.connect(self.toggle_apply_coating)
        self.ui.apply_phosphor.toggled.connect(self.toggle_apply_phosphor)

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
                self.filters[det_name]['material'] = material.name
        else:
            self.density_inputs[category].setValue(0.0)

    def filter_info_changed(self, new_value=None, det_name=None):
        if det_name is None:
            det_name = self.ui.detectors.currentText()
        self.filters[det_name]['density'] = self.ui.filter_density.value()
        self.filters[det_name]['thickness'] = self.ui.filter_thickness.value()

    def detector_changed(self, new_det):
        filter_widgets = [
            self.ui.filter_material,
            self.ui.filter_material_input,
            self.ui.filter_density,
            self.ui.filter_thickness
        ]

        with block_signals(*filter_widgets):
            # Update material inputs
            mat = self.filters[new_det]['material']
            custom_mat = mat not in self.mat_options
            self.ui.filter_material.setCurrentText(
                mat if not custom_mat else 'Enter Manually'
            )
            self.ui.filter_material_input.setText(mat if custom_mat else '')
            self.ui.filter_material_input.setEnabled(custom_mat)
            self.ui.filter_density.setEnabled(custom_mat)
            # Update filter inputs
            self.ui.filter_density.setValue(self.filters[new_det]['density'])
            self.ui.filter_thickness.setValue(
                self.filters[new_det]['thickness']
            )

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
            HexrdConfig().update_detector_coating(
                det_name,
                material=materials['coating'],
                density=self.ui.coating_density.value(),
                thickness=self.ui.coating_thickness.value()
            )
            HexrdConfig().update_detector_phosphor(
                det_name,
                material=materials['phosphor'],
                density=self.ui.phosphor_density.value(),
                thickness=self.ui.phosphor_thickness.value()
            )

    def toggle_apply_filters(self, checked):
        if not checked:
            self.ui.filter_thickness.setValue(0.0)
            for det in HexrdConfig().detector_names:
                self.filter_info_changed(det_name=det)
        self.ui.detectors.setEnabled(checked)
        self.ui.filter_material.setEnabled(checked)
        index = self.ui.filter_material.currentIndex()
        self.ui.filter_material_input.setEnabled(checked and index == 0)
        self.ui.filter_density.setEnabled(checked)
        self.ui.filter_thickness.setEnabled(checked)

    def toggle_apply_coating(self, checked):
        if not checked:
            self.ui.coating_thickness.setValue(0.0)
        self.ui.coating_material.setEnabled(checked)
        index = self.ui.coating_material.currentIndex()
        self.ui.coating_material_input.setEnabled(checked and index == 0)
        self.ui.coating_density.setEnabled(checked)
        self.ui.coating_thickness.setEnabled(checked)

    def toggle_apply_phosphor(self, checked):
        if not checked:
            self.ui.phosphor_thickness.setValue(0.0)
        self.ui.phosphor_material.setEnabled(checked)
        index = self.ui.phosphor_material.currentIndex()
        self.ui.phosphor_material_input.setEnabled(checked and index == 0)
        self.ui.phosphor_density.setEnabled(checked)
        self.ui.phosphor_thickness.setEnabled(checked)
        self.ui.phosphor_readout_length.setEnabled(checked)
        self.ui.phosphor_pre_U0.setEnabled(checked)

    def get_initial_filter_values(self):
        # Use the current value, or if none, use the default
        self.filters = {}
        instr = create_hedm_instrument()
        for det in HexrdConfig().detector_names:
            filter = HexrdConfig().detector_filter(det)
            print(f'config filter {det}: {filter.material} {filter.density} {filter.thickness}')
            if filter is None:
                filter = instr.detectors[det].filter
                print(f'default filter {det}: {filter.material} {filter.density} {filter.thickness}')
            self.filters[det] = {
                'material': filter.material,
                'density': filter.density,
                'thickness': filter.thickness
            }
