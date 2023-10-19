from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader


class AzimuthalOverlayEditor:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('azimuthal_overlay_editor.ui', parent)
        self._selected_overlay = None

        self.setup_connections()
        self.enable_inputs(False)

    def setup_connections(self):
        self.ui.fwhm.valueChanged.connect(self.update_fwhm)
        self.ui.scale.valueChanged.connect(self.update_scale)

    @property
    def selected_overlay(self):
        return self._selected_overlay

    @selected_overlay.setter
    def selected_overlay(self, overlay):
        self._selected_overlay = overlay
        if overlay is not None:
            self.ui.fwhm.setValue(overlay['fwhm'])
            self.ui.scale.setValue(overlay['scale'])
            self.ui.name_label.setText(overlay['name'])

    def enable_inputs(self, enabled=False):
        self.ui.fwhm_label.setEnabled(enabled)
        self.ui.fwhm.setEnabled(enabled)
        self.ui.scale_label.setEnabled(enabled)
        self.ui.scale.setEnabled(enabled)
        self.ui.name_label.setEnabled(enabled)

    def update_fwhm(self, value):
        self.selected_overlay['fwhm'] = value
        HexrdConfig().azimuthal_overlay_modified.emit()

    def update_scale(self, value):
        self.selected_overlay['scale'] = value
        HexrdConfig().azimuthal_overlay_modified.emit()

    def update_name_label(self, name):
        self.ui.name_label.setText(name)
        HexrdConfig().azimuthal_overlay_modified.emit()
