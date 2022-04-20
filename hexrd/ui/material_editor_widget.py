from PySide2.QtCore import Signal, QObject
from PySide2.QtWidgets import QMessageBox

import numpy as np

from hexrd import spacegroup
from hexrd.material import _angstroms

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals, set_combobox_enabled_items


class MaterialEditorWidget(QObject):

    # Emitted whenever the material is modified
    material_modified = Signal()

    def __init__(self, material, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('material_editor_widget.ui', parent)

        self.setup_space_group_widgets()

        self._material = material
        self.update_gui_from_material()

        self.setup_connections()

    def setup_connections(self):
        self.ui.lattice_type.currentIndexChanged.connect(
            self.lattice_type_changed)

        for w in self.lattice_length_widgets:
            w.valueChanged.connect(self.confirm_large_lattice_parameter)

        for widget in self.lattice_widgets:
            widget.valueChanged.connect(self.set_lattice_params)

        for widget in self.space_group_setters:
            widget.currentIndexChanged.connect(self.set_space_group)
            widget.currentIndexChanged.connect(self.enable_lattice_params)

        # Flag overlays using this material for an update
        self.material_modified.connect(
            lambda: HexrdConfig().flag_overlay_updates_for_material(
                self.material.name))

        # Emit that the ring config changed when the material is modified
        self.material_modified.connect(
            HexrdConfig().overlay_config_changed.emit)

    def setup_space_group_widgets(self):
        self.ui.lattice_type.addItems(list(spacegroup._rqpDict.keys()))

        for k in spacegroup.sgid_to_hall:
            self.ui.space_group.addItem(k)
            self.ui.hall_symbol.addItem(spacegroup.sgid_to_hall[k])
            self.ui.hermann_mauguin.addItem(spacegroup.sgid_to_hm[k])

    def update_gui_from_material(self):
        match = _space_groups_without_settings == self.material.sgnum
        sgid = np.where(match)[0][0]
        self.set_space_group(sgid)
        self.lattice_type_changed()
        self.enable_lattice_params()  # This updates the values also

    @property
    def lattice_length_widgets(self):
        return [
            self.ui.lattice_a,
            self.ui.lattice_b,
            self.ui.lattice_c,
        ]

    @property
    def lattice_angle_widgets(self):
        return [
            self.ui.lattice_alpha,
            self.ui.lattice_beta,
            self.ui.lattice_gamma,
        ]

    @property
    def lattice_widgets(self):
        return self.lattice_length_widgets + self.lattice_angle_widgets

    @property
    def space_group_setters(self):
        return [
            self.ui.space_group,
            self.ui.hall_symbol,
            self.ui.hermann_mauguin
        ]

    def block_lattice_signals(self, block=True):
        for widget in self.lattice_widgets:
            widget.blockSignals(block)

    def set_space_group(self, val):
        with block_signals(*self.space_group_setters):
            sgid = _space_groups_without_settings[val]
            for sgids, lg in spacegroup._pgDict.items():
                if sgid in sgids:
                    self.ui.laue_group.setText(lg[0])
                    break

            # Lattice type must be set first
            self.lattice_type = spacegroup._ltDict[lg[1]]

            self.ui.space_group.setCurrentIndex(val)
            self.ui.hall_symbol.setCurrentIndex(val)
            self.ui.hermann_mauguin.setCurrentIndex(val)

            self.set_material_space_group(sgid)

    def enable_lattice_params(self):
        """enable independent lattice parameters"""
        # lattice parameters are stored in the old "ValUnit" class
        self.block_lattice_signals(True)
        try:
            m = self.material
            sgid = int(self.ui.space_group.currentText().split(':')[0])

            self.set_material_space_group(sgid)

            reqp = spacegroup.SpaceGroup(m.sgnum).reqParams
            lprm = m.latticeParameters
            for i, widget in enumerate(self.lattice_widgets):
                widget.setEnabled(i in reqp)
                u = 'angstrom' if i < 3 else 'degrees'
                widget.setValue(lprm[i].getVal(u))
        finally:
            self.block_lattice_signals(False)

    @property
    def lattice_type(self):
        return self.ui.lattice_type.currentText()

    @lattice_type.setter
    def lattice_type(self, v):
        self.ui.lattice_type.setCurrentText(v)

    def lattice_type_changed(self):
        valid_space_groups = space_groups_for_lattice_type(self.lattice_type)
        enable_list = np.isin(_space_groups_without_settings,
                              valid_space_groups)

        cb_list = [
            self.ui.space_group,
            self.ui.hall_symbol,
            self.ui.hermann_mauguin,
        ]
        for cb in cb_list:
            set_combobox_enabled_items(cb, enable_list)

    def confirm_large_lattice_parameter(self):
        sender = self.sender()

        name = sender.objectName().removeprefix('lattice_')
        value = sender.value()
        threshold = 50

        if value > threshold:
            msg = (
                f'Warning: lattice parameter "{name}" was set to a '
                f'large value of "{value:.2f}" Å. This might use too '
                'many system resources. Proceed anyways?'
            )
            if QMessageBox.question(self.ui, 'HEXRD', msg) == QMessageBox.No:
                # Reset the lattice parameter value.
                self.update_gui_from_material()

    def set_lattice_params(self):
        """update all the lattice parameter boxes when one changes"""
        # note: material takes reduced set of lattice parameters but outputs
        #       all six
        self.block_lattice_signals(True)
        try:
            m = self.material
            reqp = spacegroup.SpaceGroup(m.sgnum).reqParams
            nreq = len(reqp)
            lp_red = nreq*[0.0]
            for i in range(nreq):
                boxi = self.lattice_widgets[reqp[i]]
                lp_red[i] = boxi.value()
            m.latticeParameters = lp_red
            lprm = m.latticeParameters
            for i, widget in enumerate(self.lattice_widgets):
                u = 'angstrom' if i < 3 else 'degrees'
                widget.setValue(lprm[i].getVal(u))
        finally:
            self.block_lattice_signals(False)

        self.material_modified.emit()

    def set_material_space_group(self, sgid):
        # This can be an expensive operation, so make sure it isn't
        # already equal before setting.
        if self.material.sgnum != sgid:
            if isinstance(sgid, np.integer):
                # Convert to native type
                sgid = sgid.item()

            self.material.sgnum = sgid
            self.material_modified.emit()

    def set_min_d_spacing(self):
        # This can be an expensive operation, so make sure it isn't
        # already equal before setting.
        val = self.ui.min_d_spacing.value()
        if self.material.dmin.getVal('angstrom') != val:
            self.material.dmin = _angstroms(val)
            self.material_modified.emit()

    @property
    def material(self):
        return self._material

    @material.setter
    def material(self, m):
        if m != self.material:
            self._material = m
            self.update_gui_from_material()


def space_groups_for_lattice_type(ltype):
    return _ltype_to_sgrange[ltype]


def _sgrange(min, max):
    # inclusive range
    return tuple(range(min, max + 1))


_ltype_to_sgrange = {
    'triclinic': _sgrange(1, 2),
    'monoclinic': _sgrange(3, 15),
    'orthorhombic': _sgrange(16, 74),
    'tetragonal': _sgrange(75, 142),
    'trigonal': _sgrange(143, 167),
    'hexagonal': _sgrange(168, 194),
    'cubic': _sgrange(195, 230),
}

_all_space_groups = list(spacegroup.sgid_to_hall.keys())
_space_groups_without_settings = np.array(
    [int(x.split(':')[0]) for x in _all_space_groups])
