from PySide6.QtCore import QObject, Signal

from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import set_combobox_enabled_items


class SelectItemDialog(QObject):

    accepted = Signal(str)
    rejected = Signal()

    def __init__(
        self,
        options: list,
        disable_list: list | None = None,
        window_title: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.ui = UiLoader().load_file(
            'select_item_dialog.ui', parent  # type: ignore[arg-type]
        )

        if disable_list is None:
            disable_list = []

        self.options = options
        self.disable_list = disable_list

        if window_title is not None:
            self.ui.setWindowTitle(window_title)

        self.setup_connections()

    def exec(self) -> int:
        return self.ui.exec()

    def setup_connections(self) -> None:
        self.ui.button_box.accepted.connect(self.on_accepted)
        self.ui.button_box.rejected.connect(self.on_rejected)

    def on_accepted(self) -> None:
        self.accepted.emit(self.selected_option)

    def on_rejected(self) -> None:
        self.rejected.emit()

    @property
    def selected_option(self) -> str:
        return self.ui.options.currentText()

    @property
    def options(self) -> list:
        w = self.ui.options
        return [w.itemText(i) for i in range(w.count())]

    @options.setter
    def options(self, v: list) -> None:
        w = self.ui.options
        w.clear()
        for item in v:
            w.addItem(item)

        # Make sure the disable list gets reset
        self._disable_list: list[str] = []

    @property
    def num_options(self) -> int:
        return self.ui.options.count()

    @property
    def disable_list(self) -> list:
        return self._disable_list

    @disable_list.setter
    def disable_list(self, v: list) -> None:
        if self.disable_list == v:
            return

        self._disable_list = v

        enable_list = [x not in v for x in self.options]
        set_combobox_enabled_items(self.ui.options, enable_list)
