import copy
from pathlib import Path

import h5py
import numpy as np

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict

from hexrdgui.constants import ViewType
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.tree_views.hkl_picks_tree_view import HKLPicksTreeView
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.conversions import angles_to_cart, cart_to_angles
from hexrdgui.utils.dicts import ndarrays_to_lists


class HKLPicksTreeViewDialog:

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None):
        self.ui = UiLoader().load_file('hkl_picks_tree_view_dialog.ui', parent)

        self.tree_view = HKLPicksTreeView(dictionary, coords_type, canvas,
                                          self.ui)
        self.ui.tree_view_layout.addWidget(self.tree_view)

        # Default to a hidden button box
        self.button_box_visible = False

        self.update_gui()
        self.setup_connections()

    @property
    def dictionary(self):
        return self.tree_view.model().config

    @dictionary.setter
    def dictionary(self, v):
        # Our tree view is expecting lists rather than numpy arrays.
        # Go ahead and perform the conversion...
        v = copy.deepcopy(v)
        ndarrays_to_lists(v)
        self.tree_view.model().config = v
        self.tree_view.rebuild_tree()
        self.tree_view.expand_rows()

    def setup_connections(self):
        # Use accepted/rejected so these are called before on_finished()
        self.ui.accepted.connect(self.on_finished)
        self.ui.rejected.connect(self.on_finished)

        self.ui.export_picks.clicked.connect(self.export_picks_clicked)
        self.ui.import_picks.clicked.connect(self.import_picks_clicked)
        self.ui.show_overlays.toggled.connect(HexrdConfig()._set_show_overlays)
        self.ui.show_all_picks.toggled.connect(self.show_all_picks_toggled)

        HexrdConfig().overlay_config_changed.connect(self.update_gui)

    def update_gui(self):
        self.ui.show_overlays.setChecked(HexrdConfig().show_overlays)
        self.ui.show_all_picks.setChecked(self.tree_view.show_all_picks)

    def on_finished(self):
        self.tree_view.clear_artists()
        self.tree_view.clear_highlights()

        # Must call these after clearing highlights for an update...
        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

    def exec(self):
        return self.ui.exec()

    def execlater(self):
        QTimer.singleShot(0, lambda: self.exec())

    def export_picks_clicked(self):
        selected_file, selected_filter = QFileDialog.getSaveFileName(
            self.ui, 'Export Picks', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.export_picks(selected_file)

    def export_picks(self, filename):
        filename = Path(filename)

        if filename.exists():
            filename.unlink()

        # unwrap_dict_to_h5 unfortunately modifies the data
        # make a deep copy to avoid the modification.
        export_data = {
            'angular': copy.deepcopy(self.dictionary),
            'cartesian': self.dict_with_cart_coords,
        }

        with h5py.File(filename, 'w') as wf:
            unwrap_dict_to_h5(wf, export_data)

    def import_picks_clicked(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Import Picks', HexrdConfig().working_dir,
            'HDF5 files (*.h5 *.hdf5)')

        if selected_file:
            HexrdConfig().working_dir = str(Path(selected_file).parent)
            return self.import_picks(selected_file)

    def import_picks(self, filename):
        import_data = {}
        with h5py.File(filename, 'r') as rf:
            unwrap_h5_to_dict(rf, import_data)

        cart = import_data['cartesian']
        self.validate_import_data(cart, filename)
        self.dictionary = picks_cartesian_to_angles(cart)

    def validate_import_data(self, data, filename):
        # The dict keys should match the config keys.
        if sorted(data) != sorted(self.dictionary):
            msg = (
                f'Overlay keys from imported data ({sorted(data)}) '
                f'do not match the internal keys ({sorted(self.dictionary)}).'
            )
            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise Exception(msg)

        # Use the same sorting that we already have
        ret = {k: data[k] for k in self.dictionary}

        # All detector keys should match, too.
        instr = create_hedm_instrument()
        for name, overlay_picks in data.items():
            if not all(x in instr.detectors for x in overlay_picks):
                msg = (
                    f'Imported data detector keys ({list(overlay_picks)}) do '
                    'not match internal detector keys '
                    f'({list(instr.detectors)})'
                )
                QMessageBox.critical(self.ui, 'HEXRD', msg)
                raise Exception(msg)

        # Update the validated data
        data.clear()
        data.update(ret)

    def show_all_picks_toggled(self):
        self.tree_view.show_all_picks = self.ui.show_all_picks.isChecked()

    @property
    def dict_with_cart_coords(self):
        return picks_angles_to_cartesian(self.dictionary)

    @property
    def coords_type(self):
        return self.tree_view.coords_type

    @coords_type.setter
    def coords_type(self, v):
        self.tree_view.coords_type = v

    @property
    def button_box_visible(self):
        return self.ui.button_box.isVisible()

    @button_box_visible.setter
    def button_box_visible(self, b):
        self.ui.button_box.setVisible(b)


def convert_picks(picks, conversion_function, **kwargs):
    instr = create_hedm_instrument()
    ret = copy.deepcopy(picks)
    for name, detectors in ret.items():
        is_laue = 'laue' in name
        for detector_name, hkls in detectors.items():
            panel = instr.detectors[detector_name]
            if is_laue:
                for hkl, spot in hkls.items():
                    if np.any(np.isnan(spot)):
                        # Avoid the runtime warning
                        hkls[hkl] = [np.nan, np.nan]
                    else:
                        hkls[hkl] = conversion_function([spot], panel,
                                                        **kwargs)[0]
                continue

            # Must be powder
            for hkl, line in hkls.items():
                if len(line) != 0:
                    hkls[hkl] = conversion_function(line, panel, **kwargs)

    return ret


def picks_angles_to_cartesian(picks):
    return convert_picks(picks, angles_to_cart)


def picks_cartesian_to_angles(picks):
    kwargs = {'eta_period': HexrdConfig().polar_res_eta_period}
    return convert_picks(picks, cart_to_angles, **kwargs)


def generate_picks_results(overlays, polar=True):
    pick_results = []

    for overlay in overlays:
        extras = {}
        if overlay.is_powder:
            options = {
                'tvec': overlay.tvec,
            }
            extras['tth_distortion'] = overlay.tth_distortion_dict
        elif overlay.is_laue:
            options = {
                'crystal_params': overlay.crystal_params,
                'min_energy': overlay.min_energy,
                'max_energy': overlay.max_energy,
            }

        extras['xray_source'] = overlay.xray_source

        if polar:
            picks = overlay.calibration_picks_polar
        else:
            picks = overlay.calibration_picks

        pick_results.append({
            'name': overlay.name,
            'material': overlay.material_name,
            'type': overlay.type.value,
            'options': options,
            'default_refinements': overlay.refinements,
            'picks': picks,
            **extras,
        })

    return pick_results


def overlays_to_tree_format(overlays):
    picks = generate_picks_results(overlays)
    return picks_to_tree_format(picks)


def picks_to_tree_format(all_picks):
    tree_format = {}
    for entry in all_picks:
        tree_format[entry['name']] = entry['picks']

    return tree_format


def tree_format_to_picks(overlays: list, tree_format: dict):
    # Make a dict with the names
    overlays_dict = {x.name: x for x in overlays}

    all_picks = []
    for name, entry in tree_format.items():
        overlay = overlays_dict[name]
        current = {
            'material': overlay.material,
            'type': overlay.type,
            'picks': entry,
        }
        all_picks.append(current)

    return all_picks
