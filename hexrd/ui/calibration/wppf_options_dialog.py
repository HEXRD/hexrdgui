import importlib.resources
import os
from pathlib import Path

import yaml

from PySide2.QtCore import Qt, QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QMessageBox, QSizePolicy,
    QTableWidgetItem, QWidget
)

from hexrd.ui import enter_key_filter

import hexrd.ui.resources.calibration as calibration_resources
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'name': 0,
    'value': 1,
    'minimum': 2,
    'maximum': 3,
    'vary': 4
}


class WppfOptionsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('wppf_options_dialog.ui', parent)
        self.ui.setWindowTitle('WPPF Options Dialog')
        self.ui.installEventFilter(enter_key_filter)

        self.load_initial_params()
        self.load_settings()

        self.value_spinboxes = []
        self.minimum_spinboxes = []
        self.maximum_spinboxes = []
        self.vary_checkboxes = []

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.background_method.currentIndexChanged.connect(
            self.update_visible_background_parameters)
        self.ui.select_experiment_file_button.pressed.connect(
            self.select_experiment_file)

        self.ui.accepted.connect(self.accept)
        self.ui.rejected.connect(self.reject)

    def accept(self):
        try:
            self.validate()
        except Exception as e:
            QMessageBox.critical(self.ui, 'HEXRD', str(e))
            self.show()
            return

        self.save_settings()
        self.accepted.emit()

    def reject(self):
        self.rejected.emit()

    def validate(self):
        use_experiment_file = self.use_experiment_file
        if use_experiment_file and not os.path.exists(self.experiment_file):
            raise Exception(f'Experiment file, {self.experiment_file}, '
                            'does not exist')

    def load_initial_params(self):
        text = importlib.resources.read_text(calibration_resources,
                                             'wppf_params.yml')
        self.params = yaml.load(text, Loader=yaml.FullLoader)

    def show(self):
        self.ui.show()

    def update_visible_background_parameters(self):
        is_chebyshev = self.background_method == 'chebyshev'
        chebyshev_widgets = [
            self.ui.chebyshev_polynomial_degree,
            self.ui.chebyshev_polynomial_degree_label
        ]
        for w in chebyshev_widgets:
            w.setVisible(is_chebyshev)

    @property
    def wppf_method(self):
        return self.ui.wppf_method.currentText()

    @wppf_method.setter
    def wppf_method(self, v):
        self.ui.wppf_method.setCurrentText(v)

    @property
    def refinement_steps(self):
        return self.ui.refinement_steps.value()

    @refinement_steps.setter
    def refinement_steps(self, v):
        self.ui.refinement_steps.setValue(v)

    @property
    def background_method(self):
        return self.ui.background_method.currentText()

    @background_method.setter
    def background_method(self, v):
        self.ui.background_method.setCurrentText(v)

    @property
    def chebyshev_polynomial_degree(self):
        return self.ui.chebyshev_polynomial_degree.value()

    @chebyshev_polynomial_degree.setter
    def chebyshev_polynomial_degree(self, v):
        self.ui.chebyshev_polynomial_degree.setValue(v)

    @property
    def background_method_dict(self):
        # This returns the background information in the format that
        # the WPPF classes expect in hexrd.
        method = self.background_method
        if method == 'spline':
            value = None
        elif method == 'chebyshev':
            value = self.chebyshev_polynomial_degree
        else:
            raise Exception(f'Unknown background method: {method}')

        return {method: value}

    @property
    def use_experiment_file(self):
        return self.ui.use_experiment_file.isChecked()

    @use_experiment_file.setter
    def use_experiment_file(self, b):
        self.ui.use_experiment_file.setChecked(b)

    @property
    def experiment_file(self):
        return self.ui.experiment_file.text()

    @experiment_file.setter
    def experiment_file(self, v):
        self.ui.experiment_file.setText(v)

    def load_settings(self):
        settings = HexrdConfig().config['calibration'].get('wppf')
        if not settings:
            return

        blockers = [QSignalBlocker(w) for w in self.all_widgets]  # noqa: F841
        for k, v in settings.items():
            setattr(self, k, v)

    def save_settings(self):
        settings = HexrdConfig().config['calibration'].setdefault('wppf', {})
        keys = [
            'wppf_method',
            'refinement_steps',
            'background_method',
            'chebyshev_polynomial_degree',
            'use_experiment_file',
            'experiment_file',
            'params'
        ]
        for key in keys:
            settings[key] = getattr(self, key)

    def select_experiment_file(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Select Experiment File', HexrdConfig().working_dir,
            'TXT files (*.txt)')

        if selected_file:
            path = Path(selected_file)
            HexrdConfig().working_dir = str(path.parent)
            self.ui.experiment_file.setText(selected_file)

    def create_label(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def create_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setValue(float(v))
        sb.valueChanged.connect(self.update_params)

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
        cb.toggled.connect(self.update_params)

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

    def update_gui(self):
        self.update_visible_background_parameters()
        self.update_table()

    def clear_table(self):
        self.value_spinboxes.clear()
        self.minimum_spinboxes.clear()
        self.maximum_spinboxes.clear()
        self.vary_checkboxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        blocker = QSignalBlocker(self.ui.table)  # noqa: F841

        self.clear_table()
        self.ui.table.setRowCount(len(self.params))
        for i, (name, vals) in enumerate(self.params.items()):
            w = self.create_label(name)
            self.ui.table.setItem(i, COLUMNS['name'], w)

            w = self.create_value_spinbox(vals[0])
            self.ui.table.setCellWidget(i, COLUMNS['value'], w)

            w = self.create_minimum_spinbox(vals[1])
            self.ui.table.setCellWidget(i, COLUMNS['minimum'], w)

            w = self.create_maximum_spinbox(vals[2])
            self.ui.table.setCellWidget(i, COLUMNS['maximum'], w)

            w = self.create_vary_checkbox(vals[3])
            self.ui.table.setCellWidget(i, COLUMNS['vary'], w)

    def update_params(self):
        for i, vals in enumerate(self.params.values()):
            vals[0] = self.value_spinboxes[i].value()
            vals[1] = self.minimum_spinboxes[i].value()
            vals[2] = self.maximum_spinboxes[i].value()
            vals[3] = self.vary_checkboxes[i].isChecked()

    @property
    def all_widgets(self):
        names = [
            'wppf_method',
            'refinement_steps',
            'background_method',
            'chebyshev_polynomial_degree',
            'experiment_file',
            'table'
        ]
        return [getattr(self.ui, x) for x in names]


if __name__ == '__main__':
    from PySide2.QtWidgets import QApplication

    app = QApplication()

    dialog = WppfOptionsDialog()
    dialog.ui.exec_()

    print(f'{dialog.wppf_method=}')
    print(f'{dialog.background_method=}')
    print(f'{dialog.chebyshev_polynomial_degree=}')
    print(f'{dialog.experiment_file=}')
    print(f'{dialog.params=}')
