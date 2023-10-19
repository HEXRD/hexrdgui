import numpy as np

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QWidget

from hexrdgui.scientificspinbox import ScientificDoubleSpinBox
from hexrdgui.utils import block_signals

DEFAULT_ENABLED_STYLE_SHEET = 'background-color: white'
DEFAULT_DISABLED_STYLE_SHEET = 'background-color: #F0F0F0'

INVALID_MATRIX_STYLE_SHEET = 'background-color: red'


class MatrixEditor(QWidget):

    data_modified = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)

        self._data = data

        # If this is not None, then only the elements present in the
        # list (as (i, j) items) will be enabled.
        self._enabled_elements = None

        # If this is set, it will be called every time the data updates
        # to apply equality constraints.
        self._apply_constraints_func = None

        # Whether or not the matrix is currently invalid
        self.matrix_invalid = False

        # Reason the matrix is currently invalid
        self.matrix_invalid_reason = ''

        self.setLayout(QGridLayout())
        self.add_spin_boxes()
        self.update_gui()

    def add_spin_boxes(self):
        layout = self.layout()
        for i in range(self.rows):
            for j in range(self.cols):
                sb = self.create_spin_box()
                layout.addWidget(sb, i, j)

    def create_spin_box(self):
        sb = ScientificDoubleSpinBox()
        sb.setKeyboardTracking(False)
        sb.valueChanged.connect(self.element_modified)
        return sb

    def element_modified(self):
        self.update_data()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, v):
        if not np.array_equal(self._data, v):
            if self._data.shape != v.shape:
                msg = (f'Shape {v.shape} does not match original shape '
                       f'{self._data.shape}')
                raise AttributeError(msg)

            self._data = v
            self.reset_disabled_values()
            self.update_gui()

    @property
    def rows(self):
        return self.data.shape[0]

    @property
    def cols(self):
        return self.data.shape[1]

    def update_data(self):
        self.data[:] = self.gui_data
        self.apply_constraints()
        self.data_modified.emit()

    def update_gui(self):
        self.gui_data = self.data

    @property
    def gui_data(self):
        row_range = range(self.rows)
        col_range = range(self.cols)
        return [[self.gui_value(i, j) for j in col_range] for i in row_range]

    @gui_data.setter
    def gui_data(self, v):
        with block_signals(*self.all_widgets):
            for i in range(self.rows):
                for j in range(self.cols):
                    self.set_gui_value(i, j, v[i][j])

    @property
    def all_widgets(self):
        row_range = range(self.rows)
        col_range = range(self.cols)
        return [self.widget(i, j) for j in col_range for i in row_range]

    @property
    def enabled_widgets(self):
        widgets = []
        for i in range(self.rows):
            for j in range(self.cols):
                if (i, j) in self.enabled_elements:
                    widgets.append(self.widget(i, j))

        return widgets

    def widget(self, row, col):
        return self.layout().itemAtPosition(row, col).widget()

    def gui_value(self, row, col):
        return self.widget(row, col).value()

    def set_gui_value(self, row, col, val):
        self.widget(row, col).setValue(val)

    def set_matrix_invalid(self, s):
        self.matrix_invalid = True
        self.matrix_invalid_reason = s
        self.update_tooltips()
        self.update_enable_states()

    def set_matrix_valid(self):
        self.matrix_invalid = False
        self.matrix_invalid_reason = ''
        self.update_tooltips()
        self.update_enable_states()

    def update_tooltips(self):
        if self.matrix_invalid:
            tooltip = self.matrix_invalid_reason
        else:
            tooltip = ''

        for w in self.enabled_widgets:
            w.setToolTip(tooltip)

    def update_enable_states(self):
        enable_all = self.enabled_elements is None
        for i in range(self.rows):
            for j in range(self.cols):
                w = self.widget(i, j)
                enable = enable_all or (i, j) in self.enabled_elements
                w.setEnabled(enable)

                enabled_str = 'enabled' if enable else 'disabled'
                style_sheet = getattr(self, f'{enabled_str}_style_sheet')
                w.setStyleSheet(style_sheet)

    def reset_disabled_values(self):
        # Resets all disabled values to zero, then applies constraints
        for i in range(self.rows):
            for j in range(self.cols):
                if not self.widget(i, j).isEnabled():
                    self.data[i, j] = 0.0

        self.apply_constraints()
        self.update_gui()

    @property
    def enabled_style_sheet(self):
        if self.matrix_invalid:
            return INVALID_MATRIX_STYLE_SHEET

        return DEFAULT_ENABLED_STYLE_SHEET

    @property
    def disabled_style_sheet(self):
        return DEFAULT_DISABLED_STYLE_SHEET

    @property
    def enabled_elements(self):
        return self._enabled_elements

    @enabled_elements.setter
    def enabled_elements(self, v):
        if self._enabled_elements != v:
            self._enabled_elements = v
            self.update_enable_states()
            self.reset_disabled_values()

    @property
    def apply_constraints_func(self):
        return self._apply_constraints_func

    @apply_constraints_func.setter
    def apply_constraints_func(self, v):
        if self._apply_constraints_func != v:
            self._apply_constraints_func = v
            self.apply_constraints()

    def apply_constraints(self):
        if (func := self.apply_constraints_func) is None:
            return

        func(self.data)
        self.update_gui()


if __name__ == '__main__':
    import sys

    from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout

    if len(sys.argv) < 2:
        sys.exit('Usage: <script> <matrix_size>')

    rows, cols = [int(x) for x in sys.argv[1].split('x')]
    data = np.ones((rows, cols))

    app = QApplication(sys.argv)
    dialog = QDialog()
    layout = QVBoxLayout()

    dialog.setLayout(layout)
    editor = MatrixEditor(data)
    layout.addWidget(editor)

    # def constraints(x):
    #     x[2][2] = x[1][1]

    # editor.enabled_elements = [(1, 1), (3, 4)]
    # editor.apply_constraints_func = constraints

    def on_data_modified():
        print(f'Data modified: {editor.data}')

    editor.data_modified.connect(on_data_modified)
    dialog.finished.connect(app.quit)
    dialog.show()

    app.exec()
