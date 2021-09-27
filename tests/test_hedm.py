import numpy as np

from PySide2.QtCore import Qt

from hexrd.ui.hexrd_config import HexrdConfig

from utils import select_files_when_asked


def test_load_data(qtbot, main_window, default_config_path, default_data_path):
    # Prove this gets changed
    assert 'GE' not in HexrdConfig().detectors

    # Load config file
    with select_files_when_asked(default_config_path):
        main_window.ui.action_open_config_file.triggered.emit()

    # Should have loaded the instrument config
    detectors = HexrdConfig().detectors
    assert len(detectors) == 1
    assert 'GE' in detectors

    def is_dummy_data():
        for ims in HexrdConfig().imageseries_dict.values():
            if len(ims) != 1 or not np.all(ims[0] == 1):
                return False

        return True

    # There should only be dummy data currently
    assert is_dummy_data()

    load_panel = main_window.load_widget
    # Press the "Select Image Files" button
    with select_files_when_asked(default_data_path):
        qtbot.mouseClick(load_panel.ui.image_files, Qt.LeftButton)

    qtbot.mouseClick(load_panel.ui.read, Qt.LeftButton)

    assert not is_dummy_data()
    ims = HexrdConfig().imageseries_dict['GE']
    assert len(ims) == 480
