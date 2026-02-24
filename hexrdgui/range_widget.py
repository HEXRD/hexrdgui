from PySide6.QtWidgets import QWidget

from hexrdgui.ui_loader import UiLoader


class RangeWidget:

    def __init__(self, parent: QWidget | None = None) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('range_widget.ui', parent)

    @property
    def min(self) -> float:
        return self.ui.min.value()

    @min.setter
    def min(self, v: float) -> None:
        self.ui.min.setValue(v)

    @property
    def max(self) -> float:
        return self.ui.max.value()

    @max.setter
    def max(self, v: float) -> None:
        self.ui.max.setValue(v)

    @property
    def range(self) -> tuple:
        return (self.min, self.max)

    @property
    def bounds(self) -> tuple:
        return (self.ui.min.minimum(), self.ui.max.maximum())

    @bounds.setter
    def bounds(self, v: tuple) -> None:
        self.ui.min.setMinimum(v[0])
        self.ui.max.setMaximum(v[1])

        self.ui.min.setToolTip(f'Min: {v[0]}')
        self.ui.max.setToolTip(f'Max: {v[1]}')
