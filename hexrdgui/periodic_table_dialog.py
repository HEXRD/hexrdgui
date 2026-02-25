from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from silx.gui.widgets.PeriodicTable import PeriodicTable

from hexrdgui.ui_loader import UiLoader


class PeriodicTableDialog(QDialog):

    def __init__(
        self,
        atoms_selected: list | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setLayout(QVBoxLayout(self))
        layout = self.layout()
        assert layout is not None

        self.periodic_table = PeriodicTable(self, selectable=True)
        layout.addWidget(self.periodic_table)

        self.clear_selection_button = QPushButton('Clear Selection', self)
        layout.addWidget(self.clear_selection_button)

        buttons = (
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box = QDialogButtonBox(buttons, self)
        layout.addWidget(self.button_box)

        UiLoader().install_dialog_enter_key_filters(self)

        if atoms_selected:
            self.periodic_table.setSelection(atoms_selected)

        self.setup_connections()

    def setup_connections(self) -> None:
        self.clear_selection_button.pressed.connect(self.clear_selection)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def accept(self) -> None:
        if not self.selected_atoms:
            msg = 'Please select at least one element'
            QMessageBox.critical(self, 'HEXRD', msg)
            return

        super().accept()

    @property
    def selected_atoms(self) -> list[str]:
        return [x.symbol for x in self.periodic_table.getSelection()]

    def clear_selection(self) -> None:
        for item in self.periodic_table.getSelection():
            self.periodic_table.elementToggle(item)


if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication

    app = QApplication()

    dialog = PeriodicTableDialog(['H', 'Ni', 'Ta'])
    dialog.exec()

    print(f'{dialog.selected_atoms=}')
