import numpy as np

from hexrd.ui.matrix_editor import MatrixEditor
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import apply_symmetric_constraint


class ThermalFactorEditor:
    def __init__(self, value, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('thermal_factor_editor.ui', parent)

        self.ui.tab_widget.tabBar().hide()

        self.tensor_editor = MatrixEditor(np.zeros((3, 3)), parent)
        self.tensor_editor.enabled_elements = list(zip(*np.triu_indices(3)))
        self.tensor_editor.apply_constraints_func = apply_symmetric_constraint
        self.ui.tensor_editor_layout.addWidget(self.tensor_editor)

        self.value = value

        self.setup_connections()

    def setup_connections(self):
        self.ui.is_tensor.toggled.connect(self.update_tab_widget)

    def update_tab_widget(self):
        prefix = 'tensor' if self.is_tensor else 'scalar'
        tab = getattr(self.ui, f'{prefix}_tab')
        self.ui.tab_widget.setCurrentWidget(tab)

    def exec(self):
        return self.ui.exec()

    @property
    def value(self):
        if self.is_tensor:
            return compress_symmetric_tensor(self.tensor_editor.data)
        else:
            return self.ui.scalar_value.value()

    @value.setter
    def value(self, v):
        if isinstance(v, (int, float)):
            self.is_tensor = False
            self.ui.scalar_value.setValue(v)
        elif isinstance(v, np.ndarray):
            if v.shape != (6, ):
                raise Exception(f'Invalid shape: {v.shape}')
            self.is_tensor = True
            self.tensor_editor.data = expand_symmetric_tensor(v)
        else:
            raise Exception(f'Unrecognized type: {type(v)}')

    @property
    def is_tensor(self):
        return self.ui.is_tensor.isChecked()

    @is_tensor.setter
    def is_tensor(self, v):
        self.ui.is_tensor.setChecked(v)


thermal_factor_tensor_mapping = {
    0: (0, 0),
    1: (1, 1),
    2: (2, 2),
    3: (0, 1),
    4: (0, 2),
    5: (1, 2),
}


def expand_symmetric_tensor(x):
    ret = np.zeros((3, 3), dtype=np.float64)

    for k, v in thermal_factor_tensor_mapping.items():
        ret[v] = x[k]

    apply_symmetric_constraint(ret)
    return ret


def compress_symmetric_tensor(x):
    ret = np.zeros(6, dtype=np.float64)

    for k, v in thermal_factor_tensor_mapping.items():
        ret[k] = x[v]

    return ret
