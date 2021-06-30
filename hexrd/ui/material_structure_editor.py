import copy
import re

import numpy as np

from PySide2.QtCore import (
    Qt, QItemSelectionModel, QObject, QSignalBlocker, Signal
)
from PySide2.QtWidgets import (
    QLineEdit, QItemEditorFactory, QStyledItemDelegate, QTableWidgetItem
)

from hexrd.constants import ptable, ptableinverse

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.material_site_editor import MaterialSiteEditor
from hexrd.ui.ui_loader import UiLoader


DEFAULT_SITE = {
    'name': 'Site',
    'fractional_coords': [0, 0, 0],
    'atoms': [
        {
            'symbol': 'O',
            'charge': '0',
            'occupancy': 0.5,
            'U': 1e-6
        },
        {
            'symbol': 'Ce',
            'charge': '0',
            'occupancy': 0.5,
            'U': 1e-6
        }
    ],
}


class MaterialStructureEditor(QObject):

    material_modified = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('material_structure_editor.ui', parent)

        # Hide the tab bar
        self.ui.site_editor_tab_widget.tabBar().hide()

        # Center the text when it is edited...
        self.ui.table.setItemDelegate(Delegate(self.ui.table))

        self.sites = []

        self.setup_connections()

        self.update_gui()

    def setup_connections(self):
        self.ui.add_site.pressed.connect(self.add_site)
        self.ui.remove_site.pressed.connect(self.remove_site)

        self.ui.table.cellChanged.connect(self.name_changed)
        self.ui.table.selectionModel().selectionChanged.connect(
            self.selection_changed)

        self.ui.apply.pressed.connect(self.update_material)
        self.ui.reset.pressed.connect(self.update_gui)

    def site_modified(self):
        site = copy.deepcopy(self.material_site_editor.site)
        self.sites[self.selected_row] = site
        self.material_edited()

    def name_changed(self, row, column):
        new_name = self.ui.table.item(row, column).text()

        # If there are any sites that already have this name, ignore it
        if any(x['name'] == new_name for x in self.sites):
            return

        self.sites[row]['name'] = new_name

    def selection_changed(self):
        self.update_enable_states()
        self.update_tab()
        self.update_site_editor()

    def update_gui(self):
        self.generate_sites()
        self.update_table()
        self.modified = False

    def update_enable_states(self):
        enable_remove = self.num_rows > 1 and self.selected_row is not None
        self.ui.remove_site.setEnabled(enable_remove)

    def update_tab(self):
        tab = 'empty' if self.selected_row is None else 'site_editor'
        w = self.ui.site_editor_tab_widget
        w.setCurrentWidget(getattr(self.ui, f'{tab}_tab'))

    def update_site_editor(self):
        site = copy.deepcopy(self.active_site)
        if site is None:
            return

        if not hasattr(self, 'material_site_editor'):
            self.material_site_editor = MaterialSiteEditor(site, self.ui)
            self.ui.material_site_editor_layout.addWidget(
                self.material_site_editor.ui)
            self.material_site_editor.site_modified.connect(self.site_modified)
        else:
            self.material_site_editor.site = site

    @property
    def material(self):
        return HexrdConfig().active_material

    @property
    def num_rows(self):
        return self.ui.table.rowCount()

    @property
    def active_site(self):
        row = self.selected_row
        return self.sites[row] if row is not None else None

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

    @staticmethod
    def trailing_integer(s):
        last = re.split(r'[^\d]', s)[-1]
        return int(last) if last else None

    def next_name(self, s):
        # Get a name with a trailing number at the end
        # If that name already exists, it increments the trailing number
        trailing_int = self.trailing_integer(s)
        if trailing_int is None:
            next_int = 1
        else:
            # Chop off the trailing int
            s = s[:-len(str(trailing_int))]
            next_int = trailing_int + 1

        new_name = s + str(next_int)
        if any(x['name'] == new_name for x in self.sites):
            # Try again...
            return self.next_name(new_name)

        return new_name

    def new_site(self, site):
        new = copy.deepcopy(site)
        new['name'] = self.next_name(site['name'])
        return new

    def add_site(self):
        self.sites.append(self.new_site(DEFAULT_SITE))
        self.update_table()

        # Select the newly added row
        self.select_row(len(self.sites) - 1)

        self.material_edited()

    def remove_site(self):
        selected_row = self.selected_row
        if selected_row is None:
            return

        del self.sites[selected_row]
        self.update_table()

        if self.selected_row is None:
            # Select the last row
            self.select_row(len(self.sites) - 1)

        self.material_edited()

    def create_table_widget(self, v):
        w = QTableWidgetItem(v)
        w.setTextAlignment(Qt.AlignCenter)
        return w

    def clear_table(self):
        self.ui.table.clearContents()

    def update_table(self):
        prev_selected = self.selected_row

        self.clear_table()
        if not self.sites:
            return

        block_list = [
            self.ui.table,
            self.ui.table.selectionModel()
        ]
        blockers = [QSignalBlocker(x) for x in block_list]  # noqa: F841

        self.ui.table.setRowCount(len(self.sites))
        for i, site in enumerate(self.sites):
            w = self.create_table_widget(site['name'])
            self.ui.table.setItem(i, 0, w)

        if prev_selected is not None:
            select_row = (prev_selected if prev_selected < len(self.sites)
                          else len(self.sites) - 1)
            self.select_row(select_row)

        # Just in case the selection actually changed...
        self.selection_changed()

    def update_material(self):
        # Convert the sites back to the material data format
        info_array = []
        type_array = []
        charge_array = []
        U_array = []

        for site in self.sites:
            for atom in site['atoms']:
                info_array.append((*site['fractional_coords'],
                                   atom['occupancy']))
                type_array.append(ptable[atom['symbol']])
                charge_array.append(atom['charge'])
                U_array.append(atom['U'])

        if any(isinstance(x, np.ndarray) for x in U_array):
            # Convert all to tensors
            for i, U in enumerate(U_array):
                U_array[i] = scalar_to_tensor(U)

        mat = self.material
        mat._set_atomdata(type_array, info_array, U_array)
        mat.charge = charge_array

        # Must force an update of the unit cell and structure factor
        # for the change in the charge array.
        mat._newUnitcell()
        mat.update_structure_factor()

        self.material_modified.emit()

        self.modified = False

    def generate_sites(self):
        """The sites have a structure like the following:
        {
            'name': 'NaBr1',
            'fractional_coords': [0.25, 0.25, 0.25],
            'atoms': [
                {
                    'symbol': 'Na',
                    'charge': '0',
                    'occupancy': 0.5,
                    'U': 4.18e-7
                },
                {
                    'symbol': 'Br',
                    'charge': '0',
                    'occupancy': 0.5,
                    'U': 4.18e-7
                }
            ],
        }
        """
        self.sites.clear()

        mat = self.material
        site_indices = []

        def coords_equal(v1, v2, tol=1.e-5):
            return (
                len(v1) == len(v2) and
                all(abs(x - y) < tol for x, y in zip(v1, v2))
            )

        info_array = mat._atominfo
        type_array = mat._atomtype
        charge_array = mat.charge
        U_array = mat._U

        if any(isinstance(x, np.ndarray) for x in U_array):
            # Convert some to scalars if possible
            new_U_array = []
            for U in U_array:
                new_U_array.append(tensor_to_scalar_if_diagonal(U))

            U_array = new_U_array

        for i, atom in enumerate(info_array):
            atom_coords = atom[:3]
            # Check if this one has coords that match any others before it
            match_found = False
            for indices, coords in site_indices:
                if coords_equal(atom_coords, coords):
                    indices.append(i)
                    match_found = True
                    break

            if match_found:
                continue

            # No match was found. Append this one.
            site_indices.append(([i], atom_coords))

        for indices, coords in site_indices:
            site = {}
            site['name'] = self.next_name('Site')
            site['fractional_coords'] = coords
            site['atoms'] = []

            for i in indices:
                atom = {
                    'symbol': ptableinverse[type_array[i]],
                    'charge': charge_array[i],
                    'occupancy': info_array[i][3],
                    'U': U_array[i]
                }
                site['atoms'].append(atom)

            self.sites.append(site)

    def material_edited(self):
        self.modified = True

    @property
    def modified(self):
        return self._modified

    @modified.setter
    def modified(self, b):
        self._modified = b
        self.ui.apply.setEnabled(b)
        self.ui.reset.setEnabled(b)


class Delegate(QStyledItemDelegate):
    # This is only needed to center the text when we edit it...

    def __init__(self, parent=None):
        super().__init__(parent)

        editor_factory = EditorFactory(parent)
        self.setItemEditorFactory(editor_factory)


class EditorFactory(QItemEditorFactory):
    # This is only needed to center the text when we edit it...

    def __init__(self, parent=None):
        super().__init__(self, parent)

    def createEditor(self, user_type, parent):
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignCenter)
        return editor


def scalar_to_tensor(x):
    if isinstance(x, np.ndarray) and x.shape == (6,):
        # Already a tensor
        return x

    tensor = np.zeros(6, dtype=np.float64)
    tensor[:3] = x
    return tensor


def tensor_to_scalar_if_diagonal(x):
    # This will only convert to a scalar if the tensor is diagonal
    if not isinstance(x, np.ndarray) or x.shape != (6,):
        return x

    if np.allclose(x[:3], x[0]) and np.allclose(x[3:], 0):
        # It is diagonal
        return x[0]

    # Not diagonal...
    return x
