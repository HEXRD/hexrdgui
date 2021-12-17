from PySide2.QtCore import QObject, Signal

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.grains_viewer_dialog import GrainsViewerDialog
from hexrd.ui.overlays import overlay_name
from hexrd.ui.reflections_table import ReflectionsTable
from hexrd.ui.reorder_pairs_widget import ReorderPairsWidget
from hexrd.ui.ui_loader import UiLoader


class HEDMCalibrationOptionsDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, grains_table, overlays, parent=None):
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('hedm_calibration_options_dialog.ui',
                                   parent)

        self.grains_table = grains_table
        self.overlays = overlays
        self.parent = parent

        self.overlay_grain_map = {overlay_name(o): int(g[0])
                                  for o, g in zip(overlays, grains_table)}

        self.setup_overlay_grain_pairing_widget()

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.view_grains_table.clicked.connect(self.show_grains_table)
        self.ui.choose_hkls.pressed.connect(self.choose_hkls)

        HexrdConfig().overlay_config_changed.connect(self.update_num_hkls)

        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def update_gui(self):
        config = HexrdConfig().indexing_config['fit_grains']
        self.refit_pixel_scale = config['refit'][0]
        self.refit_ome_step_scale = config['refit'][1]

        indexing_config = HexrdConfig().indexing_config

        calibration_config = indexing_config['_hedm_calibration']
        self.do_refit = calibration_config['do_refit']
        self.clobber_strain = calibration_config['clobber_strain']
        self.clobber_centroid = calibration_config['clobber_centroid']
        self.clobber_grain_Y = calibration_config['clobber_grain_Y']

        self.update_num_hkls()

    def update_config(self):
        config = HexrdConfig().indexing_config['fit_grains']
        config['refit'][0] = self.refit_pixel_scale
        config['refit'][1] = self.refit_ome_step_scale

        indexing_config = HexrdConfig().indexing_config
        calibration_config = indexing_config['_hedm_calibration']
        calibration_config['do_refit'] = self.do_refit
        calibration_config['clobber_strain'] = self.clobber_strain
        calibration_config['clobber_centroid'] = self.clobber_centroid
        calibration_config['clobber_grain_Y'] = self.clobber_grain_Y

    def show(self):
        self.ui.show()

    def on_accepted(self):
        self.update_config()
        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    @property
    def do_refit(self):
        return self.ui.do_refit.isChecked()

    @do_refit.setter
    def do_refit(self, b):
        self.ui.do_refit.setChecked(b)

    @property
    def refit_pixel_scale(self):
        return self.ui.refit_pixel_scale.value()

    @refit_pixel_scale.setter
    def refit_pixel_scale(self, v):
        self.ui.refit_pixel_scale.setValue(v)

    @property
    def refit_ome_step_scale(self):
        return self.ui.refit_ome_step_scale.value()

    @refit_ome_step_scale.setter
    def refit_ome_step_scale(self, v):
        self.ui.refit_ome_step_scale.setValue(v)

    @property
    def clobber_strain(self):
        return self.ui.clobber_strain.isChecked()

    @clobber_strain.setter
    def clobber_strain(self, b):
        self.ui.clobber_strain.setChecked(b)

    @property
    def clobber_centroid(self):
        return self.ui.clobber_centroid.isChecked()

    @clobber_centroid.setter
    def clobber_centroid(self, b):
        self.ui.clobber_strain.setChecked(b)

    @property
    def clobber_grain_Y(self):
        return self.ui.clobber_grain_Y.isChecked()

    @clobber_grain_Y.setter
    def clobber_grain_Y(self, b):
        self.ui.clobber_grain_Y.setChecked(b)

    @property
    def material(self):
        # The materials of all of the overlays must be the same.
        # Just get the first one...
        return HexrdConfig().material(self.overlays[0]['material'])

    def choose_hkls(self):
        kwargs = {
            'material': self.material,
            'title_prefix': 'Select hkls for HEDM calibration: ',
            'parent': self.ui,
        }
        self._reflections_table = ReflectionsTable(**kwargs)
        self._reflections_table.show()

    def update_num_hkls(self):
        if self.material is None:
            num_hkls = 0
        else:
            num_hkls = len(self.material.planeData.getHKLs())

        text = f'Number of hkls selected:  {num_hkls}'
        self.ui.num_hkls_selected.setText(text)

    def setup_overlay_grain_pairing_widget(self):
        num_overlays = len(self.overlays)
        if num_overlays < 2:
            # No need for this widget...
            return

        titles = ('Overlay', 'Grain ID')
        items = [(k, str(v)) for k, v in self.overlay_grain_map.items()]

        min_height = 125 if num_overlays == 2 else 160
        layout = self.ui.overlay_grain_pairing_widget_layout
        w = ReorderPairsWidget(items, titles, self.parent)
        w.ui.setMinimumHeight(min_height)
        w.items_reordered.connect(self.on_overlay_grain_pairing_changed)
        layout.addWidget(w.ui)

        self._overlay_grain_pairing_widget = w

    def on_overlay_grain_pairing_changed(self):
        w = self._overlay_grain_pairing_widget
        self.overlay_grain_map = {o: int(g) for o, g in w.items}

    def show_grains_table(self):
        if not hasattr(self, '_grains_viewer_dialog'):
            self._grains_viewer_dialog = GrainsViewerDialog(self.grains_table)

        self._grains_viewer_dialog.show()
