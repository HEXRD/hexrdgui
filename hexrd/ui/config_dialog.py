from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class ConfigDialog:
    def __init__(self, parent=None):
        self.ui = UiLoader().load_file('config_dialog.ui', parent)

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.on_accepted)

    def exec_(self):
        self.update_gui()
        self.ui.exec_()

    def update_gui(self):
        self.max_cpus_ui = self.max_cpus_config

    def update_config(self):
        self.max_cpus_config = self.max_cpus_ui

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
    def max_cpus_config(self):
        return HexrdConfig().max_cpus

    @max_cpus_config.setter
    def max_cpus_config(self, v):
        HexrdConfig().max_cpus = v
