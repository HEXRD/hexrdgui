from PySide2.QtCore import QSignalBlocker

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class OverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('overlay_editor.ui', parent)

        self._overlay = None

        self.ui.tab_widget.tabBar().hide()

        self.setup_connections()

    def setup_connections(self):
        for w in self.laue_widgets:
            w.editingFinished.connect(self.update_config)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        if self.overlay is not None:
            self.update_gui()

    @property
    def type(self):
        return self.overlay['type']

    def update_type_tab(self):
        # Take advantage of the naming scheme...
        w = getattr(self.ui, self.type + '_tab')
        self.ui.tab_widget.setCurrentWidget(w)

    def update_gui(self):
        blockers = [QSignalBlocker(w) for w in self.all_widgets]  # noqa: F841

        self.update_type_tab()

        options = self.overlay.get('options', {})
        if self.type == 'laue':
            if 'min_energy' in options:
                self.ui.laue_min_energy.setValue(options['min_energy'])
            if 'max_energy' in options:
                self.ui.laue_max_energy.setValue(options['max_energy'])

    def update_config(self):
        options = self.overlay.setdefault('options', {})
        if self.type == 'laue':
            options['min_energy'] = self.ui.laue_min_energy.value()
            options['max_energy'] = self.ui.laue_max_energy.value()
            options['crystal_params'] = self.laue_crystal_params

        if self.overlay['visible']:
            # Only cause a re-render if the overlay is visible
            HexrdConfig().overlay_config_changed.emit()

    @property
    def laue_crystal_params(self):
        return [x.value() for x in self.laue_cc_widgets]

    @property
    def powder_widgets(self):
        return []

    @property
    def laue_cc_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'laue_cc_{i}') for i in range(12)]

    @property
    def laue_widgets(self):
        return [
            self.ui.laue_min_energy,
            self.ui.laue_max_energy
        ] + self.laue_cc_widgets

    @property
    def mono_rotation_series_widgets(self):
        return []

    @property
    def tab_widgets(self):
        return [
            self.ui.tab_widget,
            self.ui.powder_tab,
            self.ui.laue_tab,
            self.ui.mono_rotation_series_tab,
        ]

    @property
    def all_widgets(self):
        return (
            self.powder_widgets +
            self.laue_widgets +
            self.mono_rotation_series_widgets +
            self.tab_widgets
        )
