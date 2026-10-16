from pathlib import Path

import numpy as np
import tifffile
import yaml

from hexrd import resources
from hexrd.instrument import HEDMInstrument

from hexrdgui import resource_loader
from hexrdgui.create_hedm_instrument import create_hedm_instrument
from hexrdgui.main_window import MainWindow

from utils import select_files_when_asked


def test_reselected_plate_gets_its_tilt_once(
    main_window: MainWindow, tmp_path: Path
) -> None:
    dialog = main_window.llnl_import_tool_dialog
    plates = ['IMAGE-PLATE-2', 'IMAGE-PLATE-3', 'IMAGE-PLATE-4']
    dialog.ui.instruments.setCurrentText('TARDIS')
    for plate in plates:
        path = tmp_path / f'{plate}.tif'
        tifffile.imwrite(path, np.zeros((750, 1250), dtype=np.float32))
        dialog.ui.image_plates.setCurrentText(plate)
        with select_files_when_asked(path):
            dialog.load_images()

        # As if the user rotated the template by 0.1 rad
        dialog.it.total_rotation = 0.1
        dialog.complete_current_selection()

    # Go back to check the first plate, and then finish
    dialog.ui.image_plates.setCurrentText(plates[0])
    dialog.import_complete()

    text = resource_loader.load_resource(resources, 'tardis_reference_config.yml')
    reference = HEDMInstrument(yaml.safe_load(text)).detectors[plates[0]]
    panel = create_hedm_instrument().detectors[plates[0]]
    rmat = reference.rmat.T @ panel.rmat
    assert np.isclose(np.arccos((np.trace(rmat) - 1) / 2), 0.1)
