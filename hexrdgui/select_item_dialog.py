from PySide6.QtCore import QObject, Signal

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import set_combobox_enabled_items


class SelectItemDialog(QObject):

    accepted = Signal(str)
    rejected = Signal()

    def __init__(self, options, disable_list=None, window_title=None, parent=None):
        super().__init__(parent)

        self.ui = UiLoader().load_file('select_item_dialog.ui', parent)

        if disable_list is None:
            disable_list = []

        self.options = options
        self.disable_list = disable_list

        if window_title is not None:
            self.ui.setWindowTitle(window_title)

        self.setup_connections()

    def exec(self):
        return self.ui.exec()

    def setup_connections(self):
        self.ui.button_box.accepted.connect(self.on_accepted)
        self.ui.button_box.rejected.connect(self.on_rejected)

    def on_accepted(self):
        self.accepted.emit(self.selected_option)

    def on_rejected(self):
        self.rejected.emit()

    @property
    def selected_option(self):
        return self.ui.options.currentText()

    @property
    def options(self):
        w = self.ui.options
        return [w.itemText(i) for i in range(w.count())]

    @options.setter
    def options(self, v):
        w = self.ui.options
        w.clear()
        for item in v:
            w.addItem(item)

        # Make sure the disable list gets reset
        self._disable_list = []

    @property
    def num_options(self):
        return self.ui.options.count()

    @property
    def disable_list(self):
        return self._disable_list

    @disable_list.setter
    def disable_list(self, v):
        if self.disable_list == v:
            return

        self._disable_list = v

        enable_list = [x not in v for x in self.options]
        set_combobox_enabled_items(self.ui.options, enable_list)
