from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal, SignalInstance
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QSpinBox, QWidget

from hexrdgui.scientificspinbox import ScientificDoubleSpinBox


class DynamicWidget(QObject):
    """Provides an interface for a dynamically created widget from a dict.

    Some of the keys currently accepted from the dict are 'label', 'type',
    'min', 'max', 'value', and 'tooltip'.
    """

    # Emitted when the value is changed
    value_changed = Signal()

    def __init__(self, description: dict[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)

        self.description = description
        self.label = label_from_description(description)
        self.widget = widget_from_description(
            description, parent  # type: ignore[arg-type]
        )

        if self.widget:
            value_changed_signal(self.widget).connect(self._on_value_changed)

    def value(self) -> Any:
        if self.widget is None:
            return None
        return widget_value(self.widget)

    def set_value(self, v: Any) -> None:
        if self.widget is None:
            return
        set_widget_value(self.widget, v)

    def _on_value_changed(self, *args: Any) -> None:
        self.value_changed.emit()


def label_from_description(x: dict[str, Any]) -> QLabel | None:
    """Dynamically create a label from a description dict.

    This will only create a label if the label could not
    be included in the regular widget.
    """
    if not x:
        return None

    if x['type'] == bool:
        # Checkbox includes a label
        return None

    return QLabel(x['label'])


def widget_from_description(x: dict[str, Any], parent: QWidget | None = None) -> QWidget | None:
    """Dynamically create a widget from a description dict.

    Some of the keys currently accepted are 'type', 'min', 'max', and
    'tooltip'.
    """
    if not x:
        return None

    if x['type'] in (int, float):
        # It's a spin box
        widget_type = QSpinBox if x['type'] == int else ScientificDoubleSpinBox
        widget = widget_type(parent=parent)
        widget.setKeyboardTracking(False)

        if 'max' in x:
            widget.setMaximum(x['max'])
        if 'min' in x:
            widget.setMinimum(x['min'])
        if 'value' in x:
            widget.setValue(x['value'])

    elif x['type'] == bool:
        widget = QCheckBox(parent=parent)  # type: ignore[assignment]
        if 'value' in x:
            widget.setChecked(x['value'])  # type: ignore[union-attr]

    if 'tooltip' in x:
        widget.setToolTip(x['tooltip'])

    return widget


def widget_value(w: QWidget) -> Any:
    if not w:
        return
    elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
        return w.value()
    elif isinstance(w, QCheckBox):
        return w.isChecked()
    else:
        raise NotImplementedError(f'Type of widget not implemented: {type(w)}')


def set_widget_value(w: QWidget, v: Any) -> None:
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        w.setValue(v)
    elif isinstance(w, QCheckBox):
        w.setChecked(v)
    else:
        raise NotImplementedError(f'Type of widget not implemented: {type(w)}')


def value_changed_signal(w: QWidget) -> SignalInstance:
    if isinstance(w, (QSpinBox, QDoubleSpinBox)):
        return w.valueChanged
    elif isinstance(w, QCheckBox):
        return w.toggled
    else:
        raise NotImplementedError(f'Type of widget not implemented: {type(w)}')
