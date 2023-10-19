from hexrdgui.ui_loader import UiLoader


class RangeWidget:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('range_widget.ui', parent)

    @property
    def min(self):
        return self.ui.min.value()

    @min.setter
    def min(self, v):
        self.ui.min.setValue(v)

    @property
    def max(self):
        return self.ui.max.value()

    @max.setter
    def max(self, v):
        self.ui.max.setValue(v)

    @property
    def range(self):
        return (self.min, self.max)

    @property
    def bounds(self):
        return (self.ui.min.minimum(), self.ui.max.maximum())

    @bounds.setter
    def bounds(self, v):
        self.ui.min.setMinimum(v[0])
        self.ui.max.setMaximum(v[1])

        self.ui.min.setToolTip(f'Min: {v[0]}')
        self.ui.max.setToolTip(f'Max: {v[1]}')
