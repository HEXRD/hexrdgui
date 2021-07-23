import numpy as np

from PySide2.QtCore import QItemSelectionModel, QObject, QSignalBlocker, Signal
from PySide2.QtWidgets import QComboBox, QSizePolicy, QTableWidgetItem

from hexrd.constants import chargestate
from hexrd.material import Material

from hexrd.ui.periodic_table_dialog import PeriodicTableDialog
from hexrd.ui.scientificspinbox import ScientificDoubleSpinBox
from hexrd.ui.ui_loader import UiLoader


COLUMNS = {
    'symbol': 0,
    'charge': 1,
    'occupancy': 2,
    'thermal_factor': 3
}

DEFAULT_U = Material.DFLT_U[0]

OCCUPATION_MIN = 0
OCCUPATION_MAX = 1

THERMAL_FACTOR_MIN = -1.e7
THERMAL_FACTOR_MAX = 1.e7

U_TO_B = 8 * np.pi ** 2
B_TO_U = 1 / U_TO_B


class MaterialSiteEditor(QObject):

    site_modified = Signal()

    def __init__(self, site, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('material_site_editor.ui', parent)

        self._site = site

        self.charge_comboboxes = []
        self.occupancy_spinboxes = []
        self.thermal_factor_spinboxes = []

        self.update_gui()

        self.setup_connections()

    def setup_connections(self):
        self.ui.select_atom_types.pressed.connect(self.select_atom_types)
        self.ui.thermal_factor_type.currentIndexChanged.connect(
            self.update_thermal_factor_header)
        self.ui.thermal_factor_type.currentIndexChanged.connect(
            self.update_gui)
        for w in self.site_settings_widgets:
            w.valueChanged.connect(self.update_config)
        self.ui.table.selectionModel().selectionChanged.connect(
            self.selection_changed)
        self.ui.remove_atom_type.pressed.connect(self.remove_selected_atom)

    def select_atom_types(self):
        dialog = PeriodicTableDialog(self.atom_types, self.ui)
        if not dialog.exec_():
            return

        self.atom_types = dialog.selected_atoms

    @property
    def site(self):
        return self._site

    @site.setter
    def site(self, v):
        self._site = v
        self.update_gui()

    @property
    def atoms(self):
        return self.site['atoms']

    @property
    def total_occupancy(self):
        return sum(x['occupancy'] for x in self.atoms)

    @property
    def fractional_coords(self):
        return self.site['fractional_coords']

    @property
    def thermal_factor_type(self):
        return self.ui.thermal_factor_type.currentText()

    def U(self, val):
        # Take a thermal factor from a spin box and convert it to U
        type = self.thermal_factor_type
        if type == 'U':
            multiplier = 1
        elif type == 'B':
            multiplier = B_TO_U
        else:
            raise Exception(f'Unknown type: {type}')

        return val * multiplier

    def B(self, val):
        # Take a thermal factor from a spin box and convert it to B
        type = self.thermal_factor_type
        if type == 'U':
            multiplier = U_TO_B
        elif type == 'B':
            multiplier = 1
        else:
            raise Exception(f'Unknown type: {type}')

        return val * multiplier

    def thermal_factor(self, atom):
        # Given an atom, return the thermal factor in either B or U
        type = self.thermal_factor_type
        if type == 'U':
            multiplier = 1
        elif type == 'B':
            multiplier = U_TO_B
        else:
            raise Exception(f'Unknown type: {type}')

        return atom['U'] * multiplier

    @property
    def atom_types(self):
        return [x['symbol'] for x in self.site['atoms']]

    @atom_types.setter
    def atom_types(self, v):
        if v == self.atom_types:
            # No changes needed...
            return

        # Reset all the occupancies
        atoms = self.atoms
        previous_u_values = {x['symbol']: x['U'] for x in atoms}
        atoms.clear()

        for symbol in v:
            # Use the previous U if available. Otherwise, use the default.
            U = previous_u_values.get(symbol, DEFAULT_U)
            atoms.append({'symbol': symbol, 'U': U})

        self.reset_occupancies()
        self.update_table()
        self.emit_site_modified_if_valid()

    @property
    def num_rows(self):
        return self.ui.table.rowCount()

    @property
    def selected_row(self):
        selected = self.ui.table.selectionModel().selectedRows()
        return selected[0].row() if selected else None

    def select_row(self, i):
        if i is None or i >= self.num_rows:
            # Out of range. Don't do anything.
            return

        # Select the row
        selection_model = self.ui.table.selectionModel()
        selection_model.clearSelection()

        model_index = selection_model.model().index(i, 0)
        command = QItemSelectionModel.Select | QItemSelectionModel.Rows
        selection_model.select(model_index, command)

    def selection_changed(self):
        self.update_enable_states()

    def update_enable_states(self):
        enable_remove = self.num_rows > 1 and self.selected_row is not None
        self.ui.remove_atom_type.setEnabled(enable_remove)

    def remove_selected_atom(self):
        if self.selected_row is None:
            return

        atom_types = self.atom_types
        del atom_types[self.selected_row]
        self.atom_types = atom_types

    def create_symbol_label(self, v):
        w = QTableWidgetItem(v)
        return w

    def create_charge_combobox(self, charge, symbol):
        cb = QComboBox(self.ui.table)

        if charge not in chargestate[symbol]:
            raise Exception(f'Invalid charge {charge} for {symbol}')

        cb.addItems(chargestate[symbol])
        cb.setCurrentText(charge)
        cb.currentIndexChanged.connect(self.update_config)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cb.setSizePolicy(size_policy)

        self.charge_comboboxes.append(cb)
        return cb

    def create_occupancy_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setMinimum(OCCUPATION_MIN)
        sb.setMaximum(OCCUPATION_MAX)
        sb.setValue(v)
        sb.valueChanged.connect(self.update_config)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sb.setSizePolicy(size_policy)

        self.occupancy_spinboxes.append(sb)
        return sb

    def create_thermal_factor_spinbox(self, v):
        sb = ScientificDoubleSpinBox(self.ui.table)
        sb.setKeyboardTracking(False)
        sb.setMinimum(THERMAL_FACTOR_MIN)
        sb.setMaximum(THERMAL_FACTOR_MAX)
        sb.setValue(v)
        sb.valueChanged.connect(self.update_config)

        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sb.setSizePolicy(size_policy)

        self.thermal_factor_spinboxes.append(sb)
        return sb

    def clear_table(self):
        self.charge_comboboxes.clear()
        self.occupancy_spinboxes.clear()
        self.thermal_factor_spinboxes.clear()
        self.ui.table.clearContents()

    def update_gui(self):
        widgets = self.site_settings_widgets
        blockers = [QSignalBlocker(w) for w in widgets]  # noqa: F841

        for i, w in enumerate(self.fractional_coords_widgets):
            w.setValue(self.fractional_coords[i])

        self.update_total_occupancy()
        self.update_table()

    def update_table(self):
        prev_selected = self.selected_row

        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        atoms = self.site['atoms']
        self.clear_table()
        self.ui.table.setRowCount(len(atoms))
        for i, atom in enumerate(atoms):
            w = self.create_symbol_label(atom['symbol'])
            self.ui.table.setItem(i, COLUMNS['symbol'], w)

            w = self.create_charge_combobox(atom['charge'], atom['symbol'])
            self.ui.table.setCellWidget(i, COLUMNS['charge'], w)

            w = self.create_occupancy_spinbox(atom['occupancy'])
            self.ui.table.setCellWidget(i, COLUMNS['occupancy'], w)

            w = self.create_thermal_factor_spinbox(self.thermal_factor(atom))
            self.ui.table.setCellWidget(i, COLUMNS['thermal_factor'], w)

        self.update_occupancy_validity()

        if prev_selected is not None:
            select_row = (prev_selected if prev_selected < self.num_rows
                          else self.num_rows - 1)
            self.select_row(select_row)

        # Just in case the selection actually changed...
        self.selection_changed()

    def update_thermal_factor_header(self):
        w = self.ui.table.horizontalHeaderItem(COLUMNS['thermal_factor'])
        w.setText(self.thermal_factor_type)

    def update_config(self):
        for i, w in enumerate(self.fractional_coords_widgets):
            self.fractional_coords[i] = w.value()

        for atom, combobox in zip(self.atoms, self.charge_comboboxes):
            atom['charge'] = combobox.currentText()

        for atom, spinbox in zip(self.atoms, self.occupancy_spinboxes):
            atom['occupancy'] = spinbox.value()

        for atom, spinbox in zip(self.atoms, self.thermal_factor_spinboxes):
            atom['U'] = self.U(spinbox.value())

        self.update_total_occupancy()
        self.update_occupancy_validity()

        self.emit_site_modified_if_valid()

    def update_total_occupancy(self):
        self.ui.total_occupancy.setValue(self.total_occupancy)

    def reset_occupancies(self):
        total = 1.0
        atoms = self.atoms
        num_atoms = len(atoms)
        for atom in atoms:
            atom['occupancy'] = total / num_atoms

        self.update_total_occupancy()
        self.update_occupancy_validity()

    @property
    def site_valid(self):
        return self.occupancies_valid

    @property
    def occupancies_valid(self):
        return self.total_occupancy <= 1.0

    def update_occupancy_validity(self):
        valid = self.occupancies_valid
        color = 'white' if valid else 'red'
        msg = '' if valid else 'Sum of occupancies must be <= 1'

        self.ui.total_occupancy.setStyleSheet(f'background-color: {color}')
        self.ui.total_occupancy.setToolTip(msg)

    def emit_site_modified_if_valid(self):
        if not self.site_valid:
            return

        self.site_modified.emit()

    @property
    def fractional_coords_widgets(self):
        return [
            self.ui.coords_x,
            self.ui.coords_y,
            self.ui.coords_z
        ]

    @property
    def site_settings_widgets(self):
        return self.fractional_coords_widgets
