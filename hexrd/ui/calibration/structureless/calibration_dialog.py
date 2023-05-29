from PySide2.QtCore import Qt, QObject, QTimer, Signal
from PySide2.QtWidgets import (
    QCheckBox, QHBoxLayout, QSizePolicy, QTableWidgetItem, QWidget
)

from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class StructurelessCalibrationDialog(QObject):

    draw_picks_toggled = Signal(bool)
    value_modified = Signal()

    edit_picks_clicked = Signal()
    save_picks_clicked = Signal()
    load_picks_clicked = Signal()
    engineering_constraints_changed = Signal(str)

    run = Signal()
    undo_run = Signal()
    finished = Signal()

    def __init__(self, params_dict, parent=None,
                 engineering_constraints=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('structureless_calibration_dialog.ui',
                                   parent)

        self._params_dict = params_dict
        self.engineering_constraints = engineering_constraints

        self.value_spinboxes = []
        self.minimum_spinboxes = []
        self.maximum_spinboxes = []
        self.vary_checkboxes = []

        self.load_settings()

        self.reset_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.draw_picks.toggled.connect(self.on_draw_picks_toggled)
        self.ui.engineering_constraints.currentIndexChanged.connect(
            self.on_engineering_constraints_changed)
        self.ui.edit_picks_button.clicked.connect(self.on_edit_picks_clicked)
        self.ui.save_picks_button.clicked.connect(self.on_save_picks_clicked)
        self.ui.load_picks_button.clicked.connect(self.on_load_picks_clicked)
        self.ui.run_button.clicked.connect(self.on_run_button_clicked)
        self.ui.undo_run_button.clicked.connect(
            self.on_undo_run_button_clicked)
        self.ui.finished.connect(self.finish)

    def show(self):
        self.ui.show()

    def hide(self):
        self.ui.hide()

    def load_settings(self):
        pass

    def clear_table(self):
        self.value_spinboxes.clear()
        self.minimum_spinboxes.clear()
        self.maximum_spinboxes.clear()
        self.vary_checkboxes.clear()
        self.ui.table.clearContents()

    def create_label(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def create_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setValue(float(v))
        sb.valueChanged.connect(self.update_config)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sb.setSizePolicy(size_policy)
        return sb

    def create_value_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.value_spinboxes.append(sb)
        return sb

    def create_minimum_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.minimum_spinboxes.append(sb)
        return sb

    def create_maximum_spinbox(self, v):
        sb = self.create_spinbox(v)
        self.maximum_spinboxes.append(sb)
        return sb

    def create_vary_checkbox(self, b):
        cb = QCheckBox(self.ui.table)
        cb.setChecked(b)
        cb.toggled.connect(self.on_checkbox_toggled)

        self.vary_checkboxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def reset_gui(self):
        self.update_table()

        column_widths = {
            'name': 235,
            'value': 175,
            'minimum': 175,
            'maximum': 175,
            'vary': 50,
        }
        for name, value in column_widths.items():
            self.ui.table.setColumnWidth(COLUMNS[name], value)

    def update_table(self):
        table = self.ui.table

        # Keep the same scroll position
        scrollbar = table.verticalScrollBar()
        scroll_value = scrollbar.value()

        with block_signals(table):
            self.clear_table()
            self.ui.table.setRowCount(len(self.params_dict))
            for i, (key, param) in enumerate(self.params_dict.items()):
                w = self.create_label(param.name)
                table.setItem(i, COLUMNS['name'], w)

                w = self.create_value_spinbox(param.value)
                table.setCellWidget(i, COLUMNS['value'], w)

                w = self.create_minimum_spinbox(param.min)
                w.setEnabled(param.vary)
                table.setCellWidget(i, COLUMNS['minimum'], w)

                w = self.create_maximum_spinbox(param.max)
                w.setEnabled(param.vary)
                table.setCellWidget(i, COLUMNS['maximum'], w)

                w = self.create_vary_checkbox(param.vary)
                table.setCellWidget(i, COLUMNS['vary'], w)

        # During event processing, it looks like the scrollbar gets resized
        # so its maximum is one less than one it actually is. Thus, if we
        # set the value to the maximum right now, it will end up being one
        # less than the actual maximum.
        # Thus, we need to post an event to the event loop to set the
        # scroll value after the other event processing. This works, but
        # the UI still scrolls back one and then to the maximum. So it
        # doesn't look that great. FIXME: figure out how to fix this.
        QTimer.singleShot(0, lambda: scrollbar.setValue(scroll_value))

    def on_checkbox_toggled(self):
        self.update_min_max_enable_states()
        self.update_config()

    def update_min_max_enable_states(self):
        for i in range(len(self.params_dict)):
            enable = self.vary_checkboxes[i].isChecked()
            self.minimum_spinboxes[i].setEnabled(enable)
            self.maximum_spinboxes[i].setEnabled(enable)

    def update_config(self):
        # If a value changes, emit a signal to indicate so
        value_changed = False
        for i, (name, param) in enumerate(self.params_dict.items()):
            if param.value != self.value_spinboxes[i].value():
                param.value = self.value_spinboxes[i].value()
                value_changed = True

            param.min = self.minimum_spinboxes[i].value()
            param.max = self.maximum_spinboxes[i].value()
            param.vary = self.vary_checkboxes[i].isChecked()

        if value_changed:
            self.value_modified.emit()

    def on_draw_picks_toggled(self, b):
        self.draw_picks_toggled.emit(b)

    def on_run_button_clicked(self):
        self.run.emit()

    def on_undo_run_button_clicked(self):
        self.undo_run.emit()

    def finish(self):
        self.finished.emit()

    @property
    def params_dict(self):
        return self._params_dict

    @params_dict.setter
    def params_dict(self, v):
        self._params_dict = v
        self.update_table()

    @property
    def undo_enabled(self):
        return self.ui.undo_run_button.isEnabled()

    @undo_enabled.setter
    def undo_enabled(self, b):
        self.ui.undo_run_button.setEnabled(b)

    @property
    def engineering_constraints(self):
        return self.ui.engineering_constraints.currentText()

    @engineering_constraints.setter
    def engineering_constraints(self, v):
        v = str(v)
        w = self.ui.engineering_constraints
        options = [w.itemText(i) for i in range(w.count())]
        if v not in options:
            raise Exception(f'Invalid engineering constraint: {v}')

        w.setCurrentText(v)

    def on_edit_picks_clicked(self):
        self.edit_picks_clicked.emit()

    def on_save_picks_clicked(self):
        self.save_picks_clicked.emit()

    def on_load_picks_clicked(self):
        self.load_picks_clicked.emit()

    def on_engineering_constraints_changed(self):
        self.engineering_constraints_changed.emit(self.engineering_constraints)


COLUMNS = {
    'name': 0,
    'value': 1,
    'minimum': 2,
    'maximum': 3,
    'vary': 4
}
