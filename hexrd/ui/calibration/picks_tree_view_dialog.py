import copy
from pathlib import Path

import h5py
import numpy as np

from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QFileDialog, QMessageBox

from hexrd.instrument import unwrap_dict_to_h5, unwrap_h5_to_dict

from hexrd.ui.constants import ViewType
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.picks_tree_view import PicksTreeView
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils.conversions import angles_to_cart, cart_to_angles


class PicksTreeViewDialog:

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None):
        self.ui = UiLoader().load_file('picks_tree_view_dialog.ui', parent)

        self.dictionary = dictionary
        self.tree_view = PicksTreeView(dictionary, coords_type, canvas,
                                       self.ui)
        self.ui.tree_view_layout.addWidget(self.tree_view)

        self.setup_connections()

    def setup_connections(self):
        self.ui.finished.connect(self.on_finished)
        self.ui.export_picks.clicked.connect(self.export_picks_clicked)
        self.ui.import_picks.clicked.connect(self.import_picks_clicked)

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
        def ndarray_to_lists(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    ndarray_to_lists(v)
                elif isinstance(v, np.ndarray):
                    d[k] = v.tolist()

        ndarray_to_lists(self.dictionary)
        self.tree_view.model().config = self.dictionary
        self.tree_view.rebuild_tree()
        self.tree_view.expand_rows()

    def validate_import_data(self, data, filename):
        # This will validate and sort the keys to match that of the
        # internal dict we already have.
        # All of the dict keys must match exactly.
        def recurse(this, other, ret, path):
            this_keys = sorted(this.keys())
            other_keys = sorted(other.keys())
            if this_keys != other_keys:
                this_keys_str = ', '.join(f'"{x}"' for x in this_keys)
                other_keys_str = ', '.join(f'"{x}"' for x in other_keys)
                msg = (
                    f'Current keys {this_keys_str} failed to match import '
                    f'data keys {other_keys_str}'
                )
                if path:
                    path_str = ' -> '.join(path)
                    msg += f' for path "{path_str}"'

                msg += f' in file "{filename}"'
                msg += '\n\nPlease be sure the same settings are being used.'
                QMessageBox.critical(self.ui, 'HEXRD', msg)
                raise Exception(msg)

            for k, v in this.items():
                if isinstance(v, dict):
                    ret[k] = {}
                    recurse(v, other[k], ret[k], path + [k])
                else:
                    ret[k] = other[k]

        ret = {}
        recurse(self.dictionary, data, ret, [])

        # Update the validated data
        data.clear()
        data.update(ret)

    @property
    def dict_with_cart_coords(self):
        return picks_angles_to_cartesian(self.dictionary)

    @property
    def coords_type(self):
        return self.tree_view.coords_type

    @coords_type.setter
    def coords_type(self, v):
        self.tree_view.coords_type = v


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
