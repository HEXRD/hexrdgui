from __future__ import annotations


from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import (
    QItemEditorFactory,
    QPushButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)


from hexrdgui.scientificspinbox import ScientificDoubleSpinBox
from hexrdgui.calibration.panel_buffer_dialog import PanelBufferDialog
from hexrdgui.tree_views.base_tree_item_model import BaseTreeItemModel
from hexrdgui import constants

BUTTON_LABEL = 'Configure Panel Buffer'


class ValueColumnDelegate(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        editor_factory = ValueColumnEditorFactory(parent)
        self.setItemEditorFactory(editor_factory)

    def createEditor(  # type: ignore[override]
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget | None:
        model = self.parent().model()  # type: ignore[attr-defined]
        item = model.get_item(index)
        key = item.data(BaseTreeItemModel.KEY_COL)
        if key == constants.BUFFER_KEY:
            edit_btn = QPushButton(BUTTON_LABEL, parent)
            edit_btn.setStyleSheet(
                'padding: 0px; border: 1px solid lightgray;'
                'border-radius: 5px; background-color: gray;'
            )

            # Disable focus. Otherwise, when the button is clicked,
            # it gains focus, and then when it loses focus, `setData()`
            # gets called with the new focus! This is highly unexpected.
            edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            dialog = None

            def _clicked() -> None:
                nonlocal dialog
                if dialog is not None:
                    dialog.ui.hide()
                    dialog = None

                # Extract out the detector, so we can update the right config
                path = model.path_to_value(item, index.column())
                detector = path[path.index('detectors') + 1]
                dialog = PanelBufferDialog(detector, self)  # type: ignore[arg-type]
                dialog.show()

            edit_btn.clicked.connect(_clicked)

            return edit_btn
        else:
            return super().createEditor(parent, option, index)

    def setEditorData(
        self,
        editor: QWidget,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        # Implement special behavior for setting editor data
        if isinstance(editor, ScientificDoubleSpinBox):
            # Set the value ourselves to ensure special behavior
            # involving NaN runs correctly.
            v = index.data(Qt.ItemDataRole.EditRole)
            return editor.setValue(v)

        return super().setEditorData(editor, index)


class ValueColumnEditorFactory(QItemEditorFactory):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(self, parent)  # type: ignore[call-arg]

    def createEditor(
        self,
        user_type: int,
        parent: QWidget,
    ) -> QWidget:
        # Normally in Qt, we'd use QVariant (like QVariant::Double) to compare
        # with the user_type integer. However, QVariant is not available in
        # PySide6, making us use roundabout methods to get the integer like
        # below.
        float_type = ScientificDoubleSpinBox.staticMetaObject.userProperty().userType()  # type: ignore[attr-defined]
        if user_type == float_type:
            return ScientificDoubleSpinBox(parent)

        return super().createEditor(user_type, parent)
