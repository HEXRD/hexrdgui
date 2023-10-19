from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout
)

from hexrdgui.utils.dialog import add_help_url


class InputDialog(QDialog):
    @classmethod
    def getItem(cls, parent, title, label, items, current=0, editable=True,
                help_url=None):
        # This is made after `QInputDialog.getItem()`, but allows for help
        # text to also be provided.
        dialog = cls(parent=parent)
        dialog.setWindowTitle(title)

        layout = QVBoxLayout()
        dialog.setLayout(layout)

        label = QLabel(label)
        layout.addWidget(label)

        combo_box = QComboBox()
        combo_box.addItems(items)
        combo_box.setCurrentIndex(current)
        combo_box.setEditable(editable)
        layout.addWidget(combo_box)

        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
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
