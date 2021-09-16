import copy
from pathlib import Path

import h5py

from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QFileDialog

from hexrd.instrument import unwrap_dict_to_h5

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.tree_views.picks_tree_view import PicksTreeView
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils.conversions import angles_to_cart


class PicksTreeViewDialog:

    def __init__(self, dictionary, canvas=None, parent=None):
        self.ui = UiLoader().load_file('picks_tree_view_dialog.ui', parent)

        self.dictionary = dictionary
        self.tree_view = PicksTreeView(dictionary, canvas, self.ui)
        self.ui.tree_view_layout.addWidget(self.tree_view)

        self.setup_connections()

    def setup_connections(self):
        self.ui.export_picks.clicked.connect(self.export_picks_clicked)
        self.ui.finished.connect(self.on_finished)

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

        export_data = {
            'angular': self.dictionary,
            'cartesian': self.dict_with_cart_coords,
        }

        with h5py.File(filename, 'w') as wf:
            unwrap_dict_to_h5(wf, export_data)

    @property
    def dict_with_cart_coords(self):
        return picks_angles_to_cartesian(self.dictionary)


def picks_angles_to_cartesian(picks):
    instr = create_hedm_instrument()
    ret = copy.deepcopy(picks)
    for name, detectors in ret.items():
        is_laue = 'laue' in name
        for detector_name, hkls in detectors.items():
            panel = instr.detectors[detector_name]
            if is_laue:
                for hkl, spot in hkls.items():
                    hkls[hkl] = angles_to_cart([spot], panel)[0]
                continue

            # Must be powder
            for hkl, line in hkls.items():
                if line:
                    hkls[hkl] = angles_to_cart(line, panel)

    return ret
