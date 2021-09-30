import copy

import numpy as np

from PySide2.QtCore import QSignalBlocker
from PySide2.QtWidgets import QCheckBox, QDoubleSpinBox

from hexrd import unitcell

from hexrd.ui.constants import DEFAULT_POWDER_REFINEMENTS
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.reflections_table import ReflectionsTable
from hexrd.ui.select_items_widget import SelectItemsWidget
from hexrd.ui.ui_loader import UiLoader


class PowderOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('powder_overlay_editor.ui', parent)

        self._overlay = None

        refinements = copy.deepcopy(DEFAULT_POWDER_REFINEMENTS)
        self.refinements_selector = SelectItemsWidget(refinements, self.ui)
        self.ui.refinements_selector_layout.addWidget(
            self.refinements_selector.ui)

        self.update_refinement_options()

        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, QDoubleSpinBox):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)

        self.ui.enable_width.toggled.connect(self.update_enable_states)
        self.refinements_selector.selection_changed.connect(
            self.update_refinements)

        self.ui.reflections_table.pressed.connect(self.show_reflections_table)

        HexrdConfig().material_tth_width_modified.connect(
            self.material_tth_width_modified_externally)

    def update_refinement_options(self):
        if self.overlay is None:
            return

        default_refinements = copy.deepcopy(DEFAULT_POWDER_REFINEMENTS)
        indices = unitcell._rqpDict[self.material.unitcell.latticeType][0]

        # Save the previous values
        prev_refinements = copy.deepcopy(self.refinements_selector.items)

        def get_prev_val(name, default=True):
            for entry in prev_refinements:
                if entry[0] == name:
                    return entry[1]

            return default

        refinements = []
        for i in indices:
            name, val = default_refinements[i]
            refinements.append((name, get_prev_val(name, default=val)))

        self.refinements_selector.items = refinements
        self.update_refinements()

    @property
    def refinements(self):
        return self.refinements_selector.items

    @refinements.setter
    def refinements(self, v):
        self.refinements_selector.items = copy.deepcopy(v)
        self.refinements_selector.update_table()

    def update_refinements(self):
        self.overlay['refinements'] = copy.deepcopy(self.refinements)

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def update_enable_states(self):
        enable_width = self.ui.enable_width.isChecked()
        self.ui.tth_width.setEnabled(enable_width)

    def update_gui(self):
        if self.overlay is None:
            return

        blockers = [QSignalBlocker(w) for w in self.widgets]  # noqa: F841

        self.tth_width_gui = self.tth_width_config
        self.offset_gui = self.offset_config

        if 'refinements' in self.overlay:
            self.refinements = self.overlay['refinements']
        else:
            self.refinements = DEFAULT_POWDER_REFINEMENTS

        self.update_enable_states()
        self.update_refinement_options()
        self.update_reflections_table()

    def update_config(self):
        self.tth_width_config = self.tth_width_gui
        self.offset_config = self.offset_gui

        self.overlay['update_needed'] = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def material(self):
        if self.overlay is None:
            return None

        name = self.overlay['material']
        return HexrdConfig().material(name)

    @property
    def tth_width_config(self):
        if self.overlay is None:
            return None

        return self.material.planeData.tThWidth

    @tth_width_config.setter
    def tth_width_config(self, v):
        if self.overlay is None:
            return

        self.material.planeData.tThWidth = v

        # All overlays that use this material will be affected
        HexrdConfig().flag_overlay_updates_for_material(self.material.name)

    @property
    def tth_width_gui(self):
        if not self.ui.enable_width.isChecked():
            return None
        return np.radians(self.ui.tth_width.value())

    @tth_width_gui.setter
    def tth_width_gui(self, v):
        enable_width = v is not None
        self.ui.enable_width.setChecked(enable_width)
        if enable_width:
            self.ui.tth_width.setValue(np.degrees(v))

    @property
    def offset_config(self):
        if self.overlay is None:
            return

        options = self.overlay.get('options', {})
        if 'tvec' not in options:
            return

        return options['tvec']

    @offset_config.setter
    def offset_config(self, v):
        if self.overlay is None:
            return

        self.overlay['options']['tvec'] = v

    @property
    def offset_gui(self):
        return [w.value() for w in self.offset_widgets]

    @offset_gui.setter
    def offset_gui(self, v):
        if v is None:
            return

        for i, w in enumerate(self.offset_widgets):
            w.setValue(v[i])

    @property
    def offset_widgets(self):
        return [getattr(self.ui, f'offset_{i}') for i in range(3)]

    @property
    def widgets(self):
        return [
            self.ui.enable_width,
            self.ui.tth_width
        ] + self.offset_widgets

    def material_tth_width_modified_externally(self, material_name):
        if not self.material:
            return

        if material_name != self.material.name:
            return

        self.update_gui()

    def update_reflections_table(self):
        if hasattr(self, '_table'):
            self._table.material = self.material

    def show_reflections_table(self):
        if not hasattr(self, '_table'):
            kwargs = {
                'material': self.material,
                'parent': self.ui,
            }
            self._table = ReflectionsTable(**kwargs)
        else:
            # Make sure the material is up to date
            self._table.material = self.material

        self._table.show()
