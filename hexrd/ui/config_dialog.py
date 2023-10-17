from PySide6.QtWidgets import QMessageBox

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class ConfigDialog:
    def __init__(self, parent=None):
        self.ui = UiLoader().load_file('config_dialog.ui', parent)

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.on_accepted)

    def exec(self):
        self.update_gui()
        self.ui.exec()

    def update_gui(self):
        self.max_cpus_ui = self.max_cpus_config
        self.font_size_ui = self.font_size_config

    def update_config(self):
        self.max_cpus_config = self.max_cpus_ui
        self.font_size_config = self.font_size_ui

    def on_accepted(self):
        self.update_config()

    @property
    def max_cpus_ui(self):
        if not self.ui.limit_cpus.isChecked():
            return None

        return self.ui.max_cpus.value()

    @max_cpus_ui.setter
    def max_cpus_ui(self, v):
        self.ui.limit_cpus.setChecked(v is not None)
        if v is None:
            return

        self.ui.max_cpus.setValue(v)

    @property
    def font_size_ui(self):
        return self.ui.font_size.value()

    @font_size_ui.setter
    def font_size_ui(self, v):
        self.ui.font_size.setValue(v)

    @property
    def max_cpus_config(self):
        return HexrdConfig().max_cpus

    @max_cpus_config.setter
    def max_cpus_config(self, v):
        HexrdConfig().max_cpus = v

    @property
    def font_size_config(self):
        return HexrdConfig().font_size

    @font_size_config.setter
    def font_size_config(self, v):
        if self.font_size_config == v:
            # Just return
            return

        # Warn the user that they must restart the application for all
        # widgets to be updated properly.
        msg = (
            'Upon changing the font size, many (but not all) widgets '
            'will update immediately.\n\nTo ensure all widgets are updated, '
            'please close the application normally via the "X" button in the '
            'top corner of the main window, and then start the application '
            'again.'
        )
        QMessageBox.warning(self.ui, 'WARNING', msg)

        HexrdConfig().font_size = v
