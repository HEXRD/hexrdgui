import math

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QComboBox

from hexrd.material import _angstroms

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.reflections_table import ReflectionsTable
from hexrdgui.material_editor_widget import MaterialEditorWidget
from hexrdgui.material_list_editor import MaterialListEditor
from hexrdgui.material_properties_editor import MaterialPropertiesEditor
from hexrdgui.material_structure_editor import MaterialStructureEditor
from hexrdgui.overlay_manager import OverlayManager
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals
from hexrdgui.utils.dialog import add_help_url


class MaterialsPanel(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('materials_panel.ui', parent)

        m = HexrdConfig().active_material
        self.material_editor_widget = MaterialEditorWidget(m, self.ui)
        self.reflections_table = ReflectionsTable(m, parent=self.ui)

        self.ui.material_editor_layout.addWidget(
            self.material_editor_widget.ui)

        self.material_structure_editor = MaterialStructureEditor(self.ui)
        self.ui.material_structure_editor_layout.addWidget(
            self.material_structure_editor.ui)

        self.material_properties_editor = MaterialPropertiesEditor(self.ui)
        self.ui.material_properties_editor_layout.addWidget(
            self.material_properties_editor.ui)

        # Turn off autocomplete for the QComboBox
        self.ui.materials_combo.setCompleter(None)

        url = 'configuration/materials/'
        add_help_url(self.ui.button_box, url)

        self.setup_connections()

        self.update_gui_from_config()

    def setup_connections(self):
        self.ui.materials_combo.installEventFilter(self)
        self.ui.materials_combo.currentIndexChanged.connect(
            self.set_active_material)
        self.ui.materials_combo.currentIndexChanged.connect(
            self.update_enable_states)
        self.ui.materials_combo.currentIndexChanged.connect(self.update_table)
        self.ui.materials_combo.lineEdit().editingFinished.connect(
            self.modify_material_name)

        self.material_editor_widget.material_modified.connect(
            self.material_edited)

        self.ui.show_reflections_table.pressed.connect(
            self.show_reflections_table)
        self.ui.show_overlay_manager.pressed.connect(self.show_overlay_manager)

        self.ui.show_overlays.toggled.connect(HexrdConfig()._set_show_overlays)

        self.ui.limit_active.toggled.connect(
            HexrdConfig().set_limit_active_rings)
        self.ui.max_tth.valueChanged.connect(self.on_max_tth_changed)
        self.ui.min_d_spacing_displayed.valueChanged.connect(
            self.on_min_d_spacing_displayed_changed)

        self.ui.min_d_spacing.valueChanged.connect(
            self.on_min_d_spacing_changed)

        HexrdConfig().new_plane_data.connect(self.update_gui_from_config)

        self.ui.limit_active.toggled.connect(self.update_enable_states)
        self.ui.limit_active.toggled.connect(self.update_material_limits)
        self.ui.limit_active.toggled.connect(self.update_table)

        HexrdConfig().active_material_changed.connect(
            self.active_material_changed)
        HexrdConfig().active_material_modified.connect(
            self.active_material_modified)
        HexrdConfig().materials_dict_modified.connect(
            self.update_gui_from_config)

        self.material_structure_editor.material_modified.connect(
            self.material_structure_edited)

        self.ui.materials_tool_button.clicked.connect(self.tool_button_clicked)

        HexrdConfig().overlay_config_changed.connect(
            self.update_gui_from_config)

    def tool_button_clicked(self):
        if not hasattr(self, '_material_list_editor'):
            self._material_list_editor = MaterialListEditor(self.ui)
        self._material_list_editor.ui.show()

    def update_enable_states(self):
        limit_active = self.ui.limit_active.isChecked()
        self.ui.max_tth.setEnabled(limit_active)
        self.ui.min_d_spacing_displayed.setEnabled(limit_active)
        self.ui.min_d_spacing_displayed_label.setEnabled(limit_active)
        self.ui.max_tth_label.setEnabled(limit_active)

    @property
    def material(self):
        return HexrdConfig().active_material

    def on_max_tth_changed(self):
        max_tth = math.radians(self.ui.max_tth.value())
        wavelength = HexrdConfig().beam_wavelength

        w = self.ui.min_d_spacing_displayed
        block_signals = w.blockSignals(True)
        try:
            # Bragg's law
            max_bragg = max_tth / 2.0
            d = wavelength / (2.0 * math.sin(max_bragg))
            w.setValue(d)
        finally:
            w.blockSignals(block_signals)

        # Update the config
        HexrdConfig().active_material_tth_max = max_tth
        self.update_table()

    def on_min_d_spacing_displayed_changed(self):
        min_d = self.ui.min_d_spacing_displayed.value()
        wavelength = HexrdConfig().beam_wavelength

        w = self.ui.max_tth
        block_signals = w.blockSignals(True)
        try:
            # Bragg's law
            theta = math.degrees(math.asin(wavelength / 2.0 / min_d))
            w.setValue(theta * 2.0)
        finally:
            w.blockSignals(block_signals)

        # Update the config
        HexrdConfig().active_material_tth_max = math.radians(theta * 2.0)
        self.update_table()

    def on_min_d_spacing_changed(self):
        mat = HexrdConfig().active_material

        mat.dmin = _angstroms(self.ui.min_d_spacing.value())
        self.active_material_modified()
        HexrdConfig().flag_overlay_updates_for_material(mat.name)
        HexrdConfig().overlay_config_changed.emit()

    def update_gui_from_config(self):
        block_list = [
            self.material_editor_widget,
            self.ui.materials_combo,
            self.ui.show_overlays,
            self.ui.min_d_spacing_displayed,
            self.ui.max_tth,
            self.ui.min_d_spacing,
            self.ui.limit_active
        ]

        with block_signals(*block_list):
            combo = self.ui.materials_combo
            current_items = [combo.itemText(x) for x in range(combo.count())]
            materials_keys = list(HexrdConfig().materials.keys())

            # If the materials in the config have changed, re-build the list
            if current_items != materials_keys:
                self.ui.materials_combo.clear()
                self.ui.materials_combo.addItems(materials_keys)

            self.material_editor_widget.material = self.material
            self.ui.materials_combo.setCurrentIndex(
                materials_keys.index(HexrdConfig().active_material_name))
            self.ui.show_overlays.setChecked(HexrdConfig().show_overlays)

            self.ui.min_d_spacing.setValue(
                self.material.dmin.getVal('angstrom'))

            self.ui.limit_active.setChecked(HexrdConfig().limit_active_rings)

        self.update_material_limits()
        self.update_table()
        self.update_enable_states()

    def active_material_modified(self):
        self.update_gui_from_config()
        self.material_editor_widget.update_gui_from_material()
        self.update_structure_tab()
        self.update_properties_tab()

    def material_edited(self):
        self.update_table()
        self.update_refinement_options()
        self.update_properties_tab()
        HexrdConfig().material_modified.emit(self.current_material())

    def material_structure_edited(self):
        self.update_table()
        self.update_properties_tab()

    def update_structure_tab(self):
        self.material_structure_editor.update_gui()

    def update_properties_tab(self):
        self.material_properties_editor.update_gui()

    def update_material_limits(self):
        max_tth = HexrdConfig().active_material_tth_max
        if max_tth is None:
            # Display the backup if it is None
            max_tth = HexrdConfig().backup_tth_max

        max_bragg = max_tth / 2.0

        # Bragg's law
        min_d_spacing_displayed = HexrdConfig().beam_wavelength / (
            2.0 * math.sin(max_bragg))

        block_list = [
            self.ui.min_d_spacing_displayed,
            self.ui.max_tth
        ]
        block_signals = [item.blockSignals(True) for item in block_list]
        try:
            self.ui.max_tth.setValue(math.degrees(max_tth))
            self.ui.min_d_spacing_displayed.setValue(min_d_spacing_displayed)
        finally:
            for b, item in zip(block_signals, block_list):
                item.blockSignals(b)

    def set_active_material(self):
        HexrdConfig().active_material = self.current_material()

    def active_material_changed(self):
        self.reflections_table.material = HexrdConfig().active_material
        self.update_gui_from_config()
        self.update_structure_tab()
        self.update_properties_tab()

    def current_material(self):
        return self.ui.materials_combo.currentText()

    def modify_material_name(self):
        combo = self.ui.materials_combo

        new_name = combo.currentText()
        names = HexrdConfig().materials.keys()

        if new_name in names:
            # Just ignore it
            return

        old_name = HexrdConfig().active_material_name
        HexrdConfig().rename_material(old_name, new_name)

        # Update the text of the combo box item in the list
        combo.setItemText(combo.currentIndex(), new_name)

    def show_reflections_table(self):
        self.reflections_table.show()

    def show_overlay_manager(self):
        if hasattr(self, '_overlay_manager'):
            self._overlay_manager.ui.close()
            del self._overlay_manager

        self._overlay_manager = OverlayManager(self.parent())
        self._overlay_manager.show()

    def update_table(self):
        HexrdConfig().update_reflections_tables.emit(self.current_material())

    def update_overlay_editor(self):
        if not hasattr(self, '_overlay_manager'):
            return

        self._overlay_manager.update_overlay_editor()

    def update_refinement_options(self):
        if not hasattr(self, '_overlay_manager'):
            return

        self._overlay_manager.update_refinement_options()

    def eventFilter(self, target, event):
        # This is almost identical to InstrumentFormViewWidget.eventFilter
        # The logic is explained there.
        # We should keep this and InstrumentFormViewWidget.eventFilter similar.
        if type(target) == QComboBox:
            if target.objectName() == 'materials_combo':
                enter_keys = [Qt.Key_Return, Qt.Key_Enter]
                if type(event) == QKeyEvent and event.key() in enter_keys:
                    widget = self.ui.materials_combo
                    widget.lineEdit().clearFocus()
                    return True

                if type(event) == QFocusEvent and event.lostFocus():
                    # This happens either if enter is pressed, or if the
                    # user tabs out.
                    widget = self.ui.materials_combo
                    items = [widget.itemText(i) for i in range(widget.count())]
                    text = widget.currentText()
                    idx = widget.currentIndex()
                    if text in items and widget.itemText(idx) != text:
                        # Prevent the QComboBox from automatically changing
                        # the index to be that of the other item in the list.
                        # This is confusing behavior, and it's not what we
                        # want here.
                        widget.setCurrentIndex(idx)
                        # Let the widget lose focus
                        return False

        return False
