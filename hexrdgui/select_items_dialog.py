from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from hexrdgui.select_items_widget import SelectItemsWidget
from hexrdgui.ui_loader import UiLoader


class SelectItemsDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))

        self.select_items_widget = SelectItemsWidget(items, parent)
        self.layout().addWidget(self.select_items_widget.ui)

        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.button_box = QDialogButtonBox(buttons, self)
        self.layout().addWidget(self.button_box)

        UiLoader().install_dialog_enter_key_filters(self)

        self.setup_connections()

    def setup_connections(self):
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    @property
    def selected_items(self):
        return self.select_items_widget.selected_items


if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication

    app = QApplication()

    items = [
        ('Item1', True),
        ('Item2', False),
        ('Item3', True),
        ('Item4', True)
    ]

    dialog = SelectItemsDialog(items)

    def selection_changed():
        print(f'Selection changed: {dialog.selected_items}')

    dialog.select_items_widget.selection_changed.connect(selection_changed)
    if dialog.exec():
        print(f'{dialog.selected_items=}')
