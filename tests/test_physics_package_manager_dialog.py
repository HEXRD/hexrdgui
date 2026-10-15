from pathlib import Path

import yaml

from hexrdgui import resource_loader
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.main_window import MainWindow
import hexrdgui.resources.calibration


def test_pxrdip_pinhole_shows_stored_values(
    main_window: MainWindow, tmp_path: Path
) -> None:
    # Load a PXRDIP instrument
    module = hexrdgui.resources.calibration
    config = yaml.safe_load(
        resource_loader.load_resource(module, 'default_pxrdip_config.yml')
    )
    config['detectors'] = {'IMAGE-PLATE-B': config['detectors']['default']}
    path = tmp_path / 'pxrdip.yml'
    path.write_text(yaml.safe_dump(config))
    HexrdConfig().load_instrument_config(str(path))

    # The default that is shown should be the one that is used
    dialog = main_window.physics_package_manager_dialog
    physics = HexrdConfig().physics_package
    dialog.show()
    assert dialog.ui.pinhole_diameter.value() == physics.pinhole_diameter == 300
    dialog.ui.hide()

    # Reopening the dialog should not reset the user's values
    HexrdConfig().update_physics_package(pinhole_diameter=250, pinhole_thickness=50)
    dialog.show()
    assert dialog.ui.pinhole_diameter.value() == 250
    assert dialog.ui.pinhole_thickness.value() == 50
    dialog.ui.hide()
