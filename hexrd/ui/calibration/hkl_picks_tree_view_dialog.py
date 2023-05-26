import copy
from pathlib import Path

import h5py
import numpy as np

from hexrd.crystallography import hklToStr

from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.hkl_picks_tree_view import HKLPicksTreeView
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils.conversions import angles_to_cart, cart_to_angles
from hexrd.ui.utils.dicts import ensure_all_keys_match, ndarrays_to_lists


class HKLPicksTreeViewDialog:

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None):
        self.ui = UiLoader().load_file('hkl_picks_tree_view_dialog.ui', parent)

        self.dictionary = dictionary
        self.tree_view = HKLPicksTreeView(dictionary, coords_type, canvas,
                                          self.ui)
        self.ui.tree_view_layout.addWidget(self.tree_view)

        # Default to a hidden button box
        self.button_box_visible = False

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.finished.connect(self.on_finished)
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

    def exec_(self):
        return self.ui.exec_()

    def exec_later(self):
        QTimer.singleShot(0, lambda: self.exec_())

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

        # Our tree view is expecting lists rather than numpy arrays.
        # Go ahead and perform the conversion...
        ndarrays_to_lists(self.dictionary)
        self.tree_view.model().config = self.dictionary
        self.tree_view.rebuild_tree()
        self.tree_view.expand_rows()

    def validate_import_data(self, data, filename):
        # This will validate and sort the keys to match that of the
        # internal dict we already have.
        # All of the dict keys must match exactly.
        try:
            ret = ensure_all_keys_match(self.dictionary, data)
        except KeyError as e:
            msg = e.args[0]
            msg += f'\nin file "{filename}"\n'
            msg += '\nPlease be sure the same settings are being used.'

            QMessageBox.critical(self.ui, 'HEXRD', msg)
            raise KeyError(msg)

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
                    hkls[hkl] = conversion_function([spot], panel, **kwargs)[0]
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


def generate_picks_results(overlays):
    pick_results = []

    for overlay in overlays:
        # Convert hkls to numpy arrays
        hkls = {k: np.asarray(v) for k, v in overlay.hkls.items()}
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

        pick_results.append({
            'material': overlay.material_name,
            'type': overlay.type.value,
            'options': options,
            'refinements': overlay.refinements_with_labels,
            'hkls': hkls,
            'picks': overlay.calibration_picks_polar,
            **extras,
        })

    return pick_results


def overlays_to_tree_format(overlays):
    picks = generate_picks_results(overlays)
    return picks_to_tree_format(picks)


def picks_to_tree_format(all_picks):
    def listify(sequence):
        sequence = list(sequence)
        for i, item in enumerate(sequence):
            if isinstance(item, tuple):
                sequence[i] = listify(item)

        return sequence

    tree_format = {}
    for entry in all_picks:
        hkl_picks = {}

        for det in entry['hkls']:
            hkl_picks[det] = {}
            for hkl, picks in zip(entry['hkls'][det], entry['picks'][det]):
                hkl_picks[det][hklToStr(hkl)] = listify(picks)

        name = f"{entry['material']} {entry['type']}"
        tree_format[name] = hkl_picks

    return tree_format


def tree_format_to_picks(tree_format):
    all_picks = []
    for name, entry in tree_format.items():
        material, type = name.split()
        hkls = {}
        picks = {}
        for det, hkl_picks in entry.items():
            hkls[det] = []
            picks[det] = []
            for hkl, cur_picks in hkl_picks.items():
                hkls[det].append(list(map(int, hkl.split())))
                picks[det].append(cur_picks)

        current = {
            'material': material,
            'type': type,
            'hkls': hkls,
            'picks': picks,
        }
        all_picks.append(current)

    return all_picks
