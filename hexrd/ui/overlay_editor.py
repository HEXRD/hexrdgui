import copy

from PySide2.QtCore import QObject, QSignalBlocker, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlay_style_picker import OverlayStylePicker
from hexrd.ui.ui_loader import UiLoader


class OverlayEditor(QObject):

    # Signal to the overlay manager to update
    update_manager_gui = Signal()

    def __init__(self, overlay, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('overlay_editor.ui', parent)

        self.ui.tab_widget.tabBar().hide()

        self.setup_type_combo_data()

        # Save a copy of everything except for the data
        self.original_overlay = copy.deepcopy(
            {k: v for k, v in overlay.items() if k != 'data'})
        self.original_overlay['data'] = {}

        self.overlay = overlay
        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.rejected.connect(self.on_rejected)
        self.ui.material.currentIndexChanged.connect(self.update_config)
        self.ui.type.currentIndexChanged.connect(self.update_type_tab)
        self.ui.type.currentIndexChanged.connect(self.update_config)
        self.ui.edit_style.pressed.connect(self.edit_style)

    def show(self):
        self.ui.show()

    def on_rejected(self):
        self.reset_overlay()

    def reset_overlay(self):
        self.overlay.clear()
        self.overlay.update(copy.deepcopy(self.original_overlay))
        self.update_gui()
        self.update_manager_gui.emit()
        HexrdConfig().overlay_config_changed.emit()

    def setup_type_combo_data(self):
        types = [
            'powder',
            'laue',
            'mono_rotation_series'
        ]

        for i, type in enumerate(types):
            self.ui.type.setItemData(i, type)

    def update_material_names(self):
        material_names = list(HexrdConfig().materials.keys())
        w = self.ui.material
        prev_names = [w.itemData(i) for i in range(w.count())]

        if material_names == prev_names:
            # Nothing to do...
            return

        blocker = QSignalBlocker(w)  # noqa: F841

        w.clear()
        for name in material_names:
            w.addItem(name, name)

        # Set the overlay material if possible
        for i in range(w.count()):
            if self.overlay['material'] == w.itemData(i):
                w.setCurrentIndex(i)
                return

        # Otherwise, update the config
        self.update_config()

    @property
    def selected_material(self):
        return self.ui.material.currentData()

    @property
    def selected_type(self):
        return self.ui.type.currentData()

    @selected_type.setter
    def selected_type(self, type):
        w = self.ui.type
        for i in range(w.count()):
            if type == w.itemData(i):
                w.setCurrentIndex(i)
                return

        raise Exception(f'Unknown type: {type}')

    def update_type_tab(self):
        # Take advantage of the naming scheme...
        w = getattr(self.ui, self.selected_type + '_tab')
        self.ui.tab_widget.setCurrentWidget(w)

    def edit_style(self):
        self._style_picker = OverlayStylePicker(self.overlay, self.ui)
        self._style_picker.ui.exec_()

    @property
    def all_widgets(self):
        return [
            self.ui.material,
            self.ui.type,
            self.ui.tab_widget,
            self.ui.powder_tab,
            self.ui.laue_tab,
            self.ui.mono_rotation_series_tab
        ]

    def update_gui(self):
        self.update_material_names()

        overlay = self.overlay
        blockers = [QSignalBlocker(w) for w in self.all_widgets]  # noqa: F841

        self.selected_type = overlay['type']
        self.update_type_tab()

    def update_config(self):
        overlay = self.overlay
        overlay['material'] = self.selected_material
        overlay['type'] = self.selected_type

        self.update_manager_gui.emit()
        HexrdConfig().overlay_config_changed.emit()
