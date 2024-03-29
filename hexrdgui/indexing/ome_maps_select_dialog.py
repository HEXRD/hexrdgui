import os

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.dialog import add_help_url


class OmeMapsSelectDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('ome_maps_select_dialog.ui', parent)
        self.ui.setWindowTitle('Load/Generate Eta Omega Maps')

        url = 'hedm/indexing/#generating-eta-omega-maps'
        add_help_url(self.ui.button_box, url)

        # Hide the tab bar. It gets selected by changes to the combo box.
        self.ui.tab_widget.tabBar().hide()
        self.setup_combo_box_data()

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().materials_dict_modified.connect(self.update_materials)
        self.ui.select_file_button.pressed.connect(self.select_file)
        self.ui.method.currentIndexChanged.connect(self.update_method_tab)
        self.ui.material.currentIndexChanged.connect(
            self.selected_material_changed)
        self.ui.choose_hkls.pressed.connect(self.choose_hkls)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

        HexrdConfig().overlay_config_changed.connect(self.update_num_hkls)

    def setup_combo_box_data(self):
        item_data = [
            'load',
            'generate'
        ]
        for i, data in enumerate(item_data):
            self.ui.method.setItemData(i, data)

        self.update_materials()

    def update_materials(self):
        prev = self.selected_material
        material_names = list(HexrdConfig().materials)

        self.ui.material.clear()
        self.ui.material.addItems(material_names)

        if prev in material_names:
            self.ui.material.setCurrentText(prev)
        else:
            self.ui.material.setCurrentText(HexrdConfig().active_material_name)

    def show(self):
        self.ui.show()

    def on_accepted(self):
        # Validate
        if self.method_name == 'load' and self.file_name == '':
            msg = 'Please select a file'
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            self.show()
            return

        # Save the selected options on the config
        self.update_config()

        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def select_file(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Load Eta Omega Maps', HexrdConfig().working_dir,
            'NPZ files (*.npz)')

        if selected_file:
            HexrdConfig().working_dir = os.path.dirname(selected_file)
            self.ui.file_name.setText(selected_file)

    @property
    def file_name(self):
        return self.ui.file_name.text()

    @property
    def threshold(self):
        if not self.ui.apply_threshold.isChecked():
            return None

        return self.ui.threshold.value()

    @threshold.setter
    def threshold(self, v):
        apply_threshold = v is not None
        self.ui.apply_threshold.setChecked(apply_threshold)
        if apply_threshold:
            self.ui.threshold.setValue(v)

    @property
    def eta_step(self):
        return self.ui.eta_step.value()

    @eta_step.setter
    def eta_step(self, v):
        self.ui.eta_step.setValue(v)

    @property
    def material_options(self):
        w = self.ui.material
        return [w.itemText(i) for i in range(w.count())]

    def selected_material_changed(self):
        if hasattr(self, '_table'):
            self._table.material = self.material

        self.update_num_hkls()

    @property
    def selected_material(self):
        return self.ui.material.currentText()

    @selected_material.setter
    def selected_material(self, name):
        if name is None or name not in self.material_options:
            return

        self.ui.material.setCurrentText(name)

    @property
    def material(self):
        return HexrdConfig().material(self.selected_material)

    @property
    def widgets(self):
        return [
            self.ui.file_name,
            self.ui.threshold,
        ]

    def update_config(self):
        # Set the new config options on the internal config
        indexing_config = HexrdConfig().indexing_config
        maps_config = indexing_config['find_orientations']['orientation_maps']
        maps_config['_select_method'] = self.method_name
        maps_config['file'] = self.file_name
        maps_config['threshold'] = self.threshold
        maps_config['eta_step'] = self.eta_step

        indexing_config['_selected_material'] = self.selected_material

    def update_gui(self):
        with block_signals(*self.widgets):
            indexing_config = HexrdConfig().indexing_config
            find_orientations = indexing_config['find_orientations']
            maps_config = find_orientations['orientation_maps']

            self.method_name = maps_config.get('_select_method', 'load')

            file_name = maps_config['file'] if maps_config['file'] else ''

            self.ui.file_name.setText(file_name)
            self.threshold = maps_config['threshold']

            self.eta_step = maps_config['eta_step']

            self.selected_material = indexing_config.get('_selected_material')

            self.update_method_tab()

            self.update_num_hkls()

    @property
    def method_name(self):
        return self.ui.method.currentData()

    @method_name.setter
    def method_name(self, v):
        w = self.ui.method
        for i in range(w.count()):
            if v == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unable to set method: {v}')

    def update_method_tab(self):
        # Take advantage of the naming scheme...
        method_tab = getattr(self.ui, self.method_name + '_tab')
        self.ui.tab_widget.setCurrentWidget(method_tab)

    def choose_hkls(self):
        kwargs = {
            'material': self.material,
            'title_prefix': 'Select hkls for eta omega map generation: ',
            'parent': self.ui,
        }
        self._table = ReflectionsTable(**kwargs)
        self._table.show()

    def update_num_hkls(self):
        if self.material is None:
            num_hkls = 0
        else:
            num_hkls = len(self.material.planeData.getHKLs())

        text = f'Number of hkls selected:  {num_hkls}'
        self.ui.num_hkls_selected.setText(text)
