import copy
import numpy as np
from numpy.linalg import LinAlgError

from PySide2.QtCore import QObject, Signal
from PySide2.QtWidgets import QFileDialog

from hexrd import instrument, matrixutil

from hexrd.ui.calibration_crystal_slider_widget import (
    CalibrationCrystalSliderWidget,
    WidgetMode as SliderWidgetMode
)
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays.constants import crystal_refinement_labels
from hexrd.ui.select_grains_dialog import SelectGrainsDialog
from hexrd.ui.select_items_widget import SelectItemsWidget
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals, convert_angle_convention


class CalibrationCrystalEditor(QObject):

    # Emitted when the params get modified
    params_modified = Signal()

    # Emitted when the refinements get modified
    refinements_modified = Signal()

    def __init__(self, params=None, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_crystal_editor.ui', parent)

        # Load slider widget
        self.slider_widget = CalibrationCrystalSliderWidget(parent=self.ui)
        self.ui.slider_widget_parent.layout().addWidget(self.slider_widget.ui)

        defaults = [(x, False) for x in crystal_refinement_labels()]
        self.refinements_selector = SelectItemsWidget(defaults, self.ui)
        self.ui.refinements_selector_layout.addWidget(
            self.refinements_selector.ui)

        self.params = params

        self.update_gui()
        self.update_orientation_suffixes()

        self.setup_connections()

    def setup_connections(self):
        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed)

        self.ui.tab_widget.currentChanged.connect(
            self.update_tab_gui)

        for w in self.all_widgets:
            w.valueChanged.connect(self.value_changed)

        self.slider_widget.changed.connect(self.slider_widget_changed)
        self.refinements_selector.selection_changed.connect(
            self.refinements_edited)

        self.ui.load.clicked.connect(self.load)
        self.ui.save.clicked.connect(self.save)

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, v):
        self._params = copy.deepcopy(v)
        self.update_gui()
        self.slider_widget.reset_ranges()

    @property
    def refinements(self):
        return [x[1] for x in self.refinements_selector.items]

    @refinements.setter
    def refinements(self, v):
        if len(v) != len(self.refinements_selector.items):
            msg = (
                f'Mismatch in {len(v)=} and '
                f'{len(self.refinements_selector.items)=}'
            )
            raise Exception(msg)

        new_items = []
        for item, value in zip(self.refinements_selector.items, v):
            new_items.append((item[0], value))

        self.refinements_selector.items = new_items

    def refinements_edited(self):
        self.refinements_modified.emit()

    def value_changed(self):
        sender = self.sender()

        if sender in self.orientation_widgets:
            self.params[:3] = self.orientation
        elif sender in self.position_widgets:
            self.params[3:6] = self.position
        else:
            # If the stretch matrix was modified, we may need to update
            # a duplicate value in the matrix.
            self.update_duplicate(sender)
            try:
                self.params[6:] = self.inverse_stretch
            except LinAlgError as e:
                self.set_matrix_invalid(str(e))
                return

            self.set_matrix_valid()

        self.params_modified.emit()

    def slider_widget_changed(self, mode, index, value):
        prefix = 'orientation' if mode == SliderWidgetMode.ORIENTATION \
            else 'position'
        name = f'{prefix}_{index}'
        w = getattr(self.ui, name)
        w.setValue(value)

    def euler_angle_convention_changed(self):
        self.update_gui()
        self.update_orientation_suffixes()

    def update_orientation_suffixes(self):
        suffix = '' if HexrdConfig().euler_angle_convention is None else '°'
        for w in self.orientation_widgets:
            w.setSuffix(suffix)
        self.slider_widget.set_orientation_suffix(suffix)

    def update_params(self):
        if self.params is None:
            return

        self.params[:3] = self.orientation
        self.params[3:6] = self.position
        self.params[6:] = self.inverse_stretch
        self.params_modified.emit()

    def update_gui(self):
        if self.params is None:
            return

        self.orientation = self.params[:3]
        self.position = self.params[3:6]
        self.inverse_stretch = self.params[6:]

        self.update_tab_gui()

    @property
    def stretch_matrix_duplicates(self):
        return {
            1: 3,
            2: 6,
            5: 7,
            7: 5,
            6: 2,
            3: 1
        }

    def update_duplicate(self, w):
        ind = int(w.objectName().replace('stretch_matrix_', ''))
        dup_ind = self.stretch_matrix_duplicates.get(ind)
        if dup_ind is not None:
            dup = getattr(self.ui, f'stretch_matrix_{dup_ind}')
            with block_signals(dup):
                dup.setValue(w.value())

    def set_matrix_valid(self):
        self.set_matrix_style_sheet('background-color: white')
        self.set_matrix_tooltips('')

    def set_matrix_invalid(self, msg=''):
        self.set_matrix_style_sheet('background-color: red')
        self.set_matrix_tooltips(msg)

    def set_matrix_style_sheet(self, s):
        for w in self.stretch_matrix_widgets:
            w.setStyleSheet(s)

    def set_matrix_tooltips(self, s):
        for w in self.stretch_matrix_widgets:
            w.setToolTip(s)

    @staticmethod
    def convert_angle_convention(values, old_conv, new_conv):
        values[:] = convert_angle_convention(values, old_conv, new_conv)

    @property
    def orientation(self):
        # This automatically converts from Euler angle conventions
        values = [x.value() for x in self.orientation_widgets]
        if HexrdConfig().euler_angle_convention is not None:
            values = np.radians(values)
            convention = HexrdConfig().euler_angle_convention
            self.convert_angle_convention(values, convention, None)

        return values

    @orientation.setter
    def orientation(self, v):
        # This automatically converts to Euler angle conventions
        if HexrdConfig().euler_angle_convention is not None:
            v = copy.deepcopy(v)
            convention = HexrdConfig().euler_angle_convention
            self.convert_angle_convention(v, None, convention)
            v = np.degrees(v)

        for i, w in enumerate(self.orientation_widgets):
            with block_signals(w):
                w.setValue(v[i])

    @property
    def position(self):
        return [x.value() for x in self.position_widgets]

    @position.setter
    def position(self, v):
        for i, w in enumerate(self.position_widgets):
            with block_signals(w):
                w.setValue(v[i])

    @property
    def inverse_stretch(self):
        m = np.array(self.stretch_matrix).reshape(3, 3)
        return matrixutil.symmToVecMV(np.linalg.inv(m), scale=True)

    @inverse_stretch.setter
    def inverse_stretch(self, v):
        m = matrixutil.vecMVToSymm(v, scale=True)
        self.stretch_matrix = np.linalg.inv(m).flatten()

    @property
    def stretch_matrix(self):
        return [x.value() for x in self.stretch_matrix_widgets]

    @stretch_matrix.setter
    def stretch_matrix(self, v):
        for i, w in enumerate(self.stretch_matrix_widgets):
            with block_signals(w):
                w.setValue(v[i])

    @property
    def orientation_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'orientation_{i}') for i in range(3)]

    @property
    def position_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'position_{i}') for i in range(3)]

    @property
    def stretch_matrix_widgets(self):
        # Take advantage of the naming scheme
        return [getattr(self.ui, f'stretch_matrix_{i}') for i in range(9)]

    @property
    def all_widgets(self):
        return (
            self.orientation_widgets +
            self.position_widgets +
            self.stretch_matrix_widgets
        )

    def update_tab_gui(self):
        """Updates slider tab contents when it becomes current tab."""
        current_widget = self.ui.tab_widget.currentWidget()
        if current_widget is self.ui.slider_tab:
            o_values = [x.value() for x in self.orientation_widgets]
            p_values = [x.value() for x in self.position_widgets]
            self.slider_widget.update_gui(o_values, p_values)

    def load(self):
        dialog = SelectGrainsDialog(1, self.ui)
        if not dialog.exec_():
            return

        self.load_from_grain(dialog.selected_grain)

    def load_from_grain(self, grain):
        self.params = grain[3:15]
        self.params_modified.emit()

    def save(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Save Crystal Parameters', HexrdConfig().working_dir,
            'Grains.out files (*.out)')

        if not selected_file:
            return

        self.write_params(selected_file)

    def write_params(self, filepath):
        gw = instrument.GrainDataWriter(filepath)
        try:
            gw.dump_grain(0, 1, 0, self.params)
        finally:
            gw.close()
