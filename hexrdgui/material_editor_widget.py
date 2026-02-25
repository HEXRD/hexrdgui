from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import QMessageBox, QWidget

import numpy as np

from hexrd.material import spacegroup
from hexrd.material import _angstroms

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals, set_combobox_enabled_items

if TYPE_CHECKING:
    from hexrd.material import Material


class MaterialEditorWidget(QObject):

    # Emitted whenever the material is modified
    material_modified = Signal()

    def __init__(self, material: Material, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('material_editor_widget.ui', parent)

        self.setup_space_group_widgets()

        self._material = material
        self.update_gui_from_material()

        # Hide the space group setting stuff, because right now, it is not
        # actually used for anything. We can bring it back if we start to
        # use it for something.
        self.ui.space_group_setting_label.hide()
        self.ui.space_group_setting.hide()

        self.setup_connections()

    def setup_connections(self) -> None:
        self.ui.lattice_type.currentIndexChanged.connect(self.lattice_type_changed)

        for w in self.lattice_length_widgets:
            w.valueChanged.connect(self.lattice_length_modified)

        for w in self.lattice_angle_widgets:
            w.valueChanged.connect(self.lattice_angle_modified)

        self.ui.space_group.currentIndexChanged.connect(
            self.space_group_number_modified
        )

        self.ui.space_group_setting.currentIndexChanged.connect(
            self.space_group_setting_modified
        )

        full_idx_setters = [
            self.ui.hall_symbol,
            self.ui.hermann_mauguin,
        ]
        for w in full_idx_setters:
            w.currentIndexChanged.connect(self.set_space_group)
            w.currentIndexChanged.connect(self.enable_lattice_params)

        self.ui.c_to_a.valueChanged.connect(self.c_to_a_ratio_modified)

        # Flag overlays using this material for an update
        self.material_modified.connect(
            lambda: HexrdConfig().flag_overlay_updates_for_material(self.material.name)
        )

        # Emit that the ring config changed when the material is modified
        self.material_modified.connect(HexrdConfig().overlay_config_changed.emit)

    def setup_space_group_widgets(self) -> None:
        self.ui.lattice_type.addItems(list(spacegroup._rqpDict.keys()))

        for i in range(230):
            self.ui.space_group.addItem(str(i + 1), i + 1)

        for k in spacegroup.sgid_to_hall:
            self.ui.hall_symbol.addItem(spacegroup.sgid_to_hall[k])
            self.ui.hermann_mauguin.addItem(spacegroup.sgid_to_hm[k])

    def update_gui_from_material(self) -> None:
        self.set_space_group_number(self.material.sgnum)
        self.lattice_type_changed()
        self.enable_lattice_params()  # This updates the values also

    @property
    def lattice_length_widgets(self) -> list[Any]:
        return [
            self.ui.lattice_a,
            self.ui.lattice_b,
            self.ui.lattice_c,
        ]

    @property
    def lattice_angle_widgets(self) -> list[Any]:
        return [
            self.ui.lattice_alpha,
            self.ui.lattice_beta,
            self.ui.lattice_gamma,
        ]

    @property
    def lattice_widgets(self) -> list[Any]:
        return self.lattice_length_widgets + self.lattice_angle_widgets

    @property
    def space_group_setters(self) -> list[Any]:
        return [
            self.ui.space_group,
            self.ui.hall_symbol,
            self.ui.hermann_mauguin,
            self.ui.space_group_setting,
        ]

    @property
    def sgnum(self) -> int:
        return self.ui.space_group.currentData()

    @sgnum.setter
    def sgnum(self, sgnum: int) -> None:
        self.ui.space_group.setCurrentIndex(sgnum - 1)

    def space_group_number_modified(self) -> None:
        self.set_space_group_number(self.sgnum)
        self.enable_lattice_params()

    def set_space_group_number(self, sgnum: int) -> None:
        match = _space_groups_without_settings == sgnum
        sgid = np.where(match)[0][0]
        self.set_space_group(sgid)

    def set_space_group(self, val: int) -> None:
        with block_signals(*self.space_group_setters):
            sgid = _space_groups_without_settings[val]
            for sgids, lg in spacegroup._pgDict.items():
                if sgid in sgids:
                    self.ui.laue_group.setText(lg[0])
                    break

            # Lattice type must be set first
            self.lattice_type = spacegroup._ltDict[lg[1]]

            self.ui.space_group.setCurrentIndex(sgid - 1)
            self.reset_space_group_settings()
            self.set_space_group_setting_by_idx(val)

            self.ui.hall_symbol.setCurrentIndex(val)
            self.ui.hermann_mauguin.setCurrentIndex(val)

            self.set_material_space_group(sgid)

        self.update_c_to_a_enable_state()

    def reset_space_group_settings(self) -> None:
        self.ui.space_group_setting.clear()
        match = _space_groups_without_settings == self.sgnum
        indices = np.where(match)[0]
        for idx in indices:
            key = _all_space_groups[idx]
            if ':' in key:
                setting = key.split(':')[1]
            else:
                setting = 'None'
            self.ui.space_group_setting.addItem(setting, int(idx))

    def set_space_group_setting_by_idx(self, idx: int) -> None:
        local_idx = self.ui.space_group_setting.findData(int(idx))
        self.ui.space_group_setting.setCurrentIndex(local_idx)

    def space_group_setting_modified(self) -> None:
        idx = self.ui.space_group_setting.currentData()
        self.set_space_group(idx)

    def enable_lattice_params(self) -> None:
        """enable independent lattice parameters"""
        # lattice parameters are stored in the old "ValUnit" class
        with block_signals(*self.lattice_widgets, self.ui.c_to_a):
            m = self.material
            self.set_material_space_group(self.sgnum)

            reqp = spacegroup.SpaceGroup(m.sgnum).reqParams
            lprm = m.latticeParameters
            for i, widget in enumerate(self.lattice_widgets):
                widget.setEnabled(i in reqp)
                u = 'angstrom' if i < 3 else 'degrees'
                widget.setValue(lprm[i].getVal(u))

            self.update_c_to_a_ratio()

    @property
    def lattice_type(self) -> str:
        return self.ui.lattice_type.currentText()

    @lattice_type.setter
    def lattice_type(self, v: str) -> None:
        self.ui.lattice_type.setCurrentText(v)

    def lattice_type_changed(self) -> None:
        valid_space_groups = space_groups_for_lattice_type(self.lattice_type)

        # First, do the enable list for the space group combo box
        enable_list = np.isin(_sgrange(1, 230), valid_space_groups)
        set_combobox_enabled_items(self.ui.space_group, enable_list)

        # Now, do the enable list for the other combo boxes
        enable_list = np.isin(_space_groups_without_settings, valid_space_groups)

        cb_list = [
            self.ui.hall_symbol,
            self.ui.hermann_mauguin,
        ]
        for cb in cb_list:
            set_combobox_enabled_items(cb, enable_list)

    def lattice_length_modified(self) -> None:
        self.confirm_large_lattice_parameter()
        self.c_or_a_modified()
        self.set_lattice_params()

    def lattice_angle_modified(self) -> None:
        self.set_lattice_params()

    def confirm_large_lattice_parameter(self) -> None:
        sender = self.sender()

        name = sender.objectName().removeprefix('lattice_')
        value = sender.value()  # type: ignore[attr-defined]
        threshold = 50

        if value > threshold:
            msg = (
                f'Warning: lattice parameter "{name}" was set to a '
                f'large value of "{value:.2f}" Å. This might use too '
                'many system resources. Proceed anyways?'
            )
            if (
                QMessageBox.question(self.ui, 'HEXRD', msg)
                == QMessageBox.StandardButton.No
            ):
                # Reset the lattice parameter value.
                self.update_gui_from_material()

    def c_or_a_modified(self) -> None:
        w_a = self.ui.lattice_a
        w_c = self.ui.lattice_c

        # Verify this is true
        w = self.sender()
        if w not in (w_a, w_c):
            return

        if not self.fix_c_to_a:
            # We need to update the c_to_a ratio
            self.update_c_to_a_ratio()
            return

        # We need to modify the opposite widget to keep c_to_a the same
        c_to_a = self.ui.c_to_a.value()
        other_w = w_a if w is w_c else w_c
        other_v = w_a.value() * c_to_a if w is w_a else w_c.value() / c_to_a
        with block_signals(other_w):
            other_w.setValue(other_v)

    def update_c_to_a_ratio(self) -> None:
        w = self.ui.c_to_a
        c = self.ui.lattice_c.value()
        a = self.ui.lattice_a.value()
        with block_signals(w):
            w.setValue(c / a)

    def c_to_a_ratio_modified(self) -> None:
        c_to_a = self.ui.c_to_a.value()
        c = self.ui.lattice_c.value()
        self.ui.lattice_a.setValue(c / c_to_a)

    @property
    def fix_c_to_a(self) -> bool:
        return self.c_to_a_ratio_enabled and self.ui.fix_c_to_a.isChecked()

    @property
    def c_to_a_ratio_enabled(self) -> bool:
        return 75 <= self.sgnum <= 194

    def update_c_to_a_enable_state(self) -> None:
        self.ui.c_to_a_ratio_group.setEnabled(self.c_to_a_ratio_enabled)

    def set_lattice_params(self) -> None:
        """update all the lattice parameter boxes when one changes"""
        # note: material takes reduced set of lattice parameters but outputs
        #       all six
        with block_signals(*self.lattice_widgets, self.ui.c_to_a):
            m = self.material
            reqp = spacegroup.SpaceGroup(m.sgnum).reqParams
            nreq = len(reqp)
            lp_red = nreq * [0.0]
            for i in range(nreq):
                boxi = self.lattice_widgets[reqp[i]]
                lp_red[i] = boxi.value()
            m.latticeParameters = lp_red
            lprm = m.latticeParameters
            for i, widget in enumerate(self.lattice_widgets):
                u = 'angstrom' if i < 3 else 'degrees'
                widget.setValue(lprm[i].getVal(u))

            self.update_c_to_a_ratio()

        self.material_modified.emit()

    def set_material_space_group(self, sgid: int) -> None:
        # This can be an expensive operation, so make sure it isn't
        # already equal before setting.
        if self.material.sgnum != sgid:
            if isinstance(sgid, np.integer):
                # Convert to native type
                sgid = sgid.item()

            self.material.sgnum = sgid
            self.material_modified.emit()

    def set_min_d_spacing(self) -> None:
        # This can be an expensive operation, so make sure it isn't
        # already equal before setting.
        val = self.ui.min_d_spacing.value()
        if self.material.dmin.getVal('angstrom') != val:
            self.material.dmin = _angstroms(val)
            self.material_modified.emit()

    @property
    def material(self) -> Material:
        return self._material

    @material.setter
    def material(self, m: Material) -> None:
        if m != self.material:
            self._material = m
            self.update_gui_from_material()


def space_groups_for_lattice_type(ltype: str) -> tuple[int, ...]:
    return _ltype_to_sgrange[ltype]


def _sgrange(min: int, max: int) -> tuple[int, ...]:
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
    [int(x.split(':')[0]) for x in _all_space_groups]
)
