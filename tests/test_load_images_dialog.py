import pytest

from hexrdgui import load_images_dialog
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.load_images_dialog import LoadImagesDialog


def test_load_images_dialog_several_files_per_detector(qtbot, monkeypatch):
    # Two files for a single detector used to raise an IndexError
    config = type(HexrdConfig())
    monkeypatch.setattr(config, 'detector_names', property(lambda _: ['detector_1']))
    monkeypatch.setattr(config, 'instrument_has_roi', property(lambda _: False))
    monkeypatch.setattr(HexrdConfig(), 'load_panel_state', {'trans': [0]})

    files = [['/data/scan_1.tif', '/data/scan_2.tif']]
    dialog = LoadImagesDialog(files, manual_assign=True)
    assert dialog.results() == {'detector_1': files[0]}

    # Accepting the dialog must pass its validation
    def warning(*args):
        pytest.fail(args[-1])

    monkeypatch.setattr(dialog.ui, 'exec', lambda: True)
    monkeypatch.setattr(load_images_dialog.QMessageBox, 'warning', warning)
    assert dialog.exec()
