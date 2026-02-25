from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from hexrdgui.utils.dialog import add_help_url


class InputDialog(QDialog):
    @classmethod
    def getItem(
        cls,
        parent: QWidget | None,
        title: str,
        label: str,
        items: Any,
        current: int = 0,
        editable: bool = True,
        help_url: str | None = None,
    ) -> tuple[str | None, bool]:
        # This is made after `QInputDialog.getItem()`, but allows for help
        # text to also be provided.
        dialog = cls(parent=parent)
        dialog.setWindowTitle(title)

        layout = QVBoxLayout()
        dialog.setLayout(layout)

        label_widget = QLabel(label)
        layout.addWidget(label_widget)

        combo_box = QComboBox()
        combo_box.addItems(items)
        combo_box.setCurrentIndex(current)
        combo_box.setEditable(editable)
        layout.addWidget(combo_box)

        buttons = (
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if help_url:
            add_help_url(button_box, help_url)

        if not dialog.exec():
            return None, False

        name = combo_box.currentText()
        return name, True
