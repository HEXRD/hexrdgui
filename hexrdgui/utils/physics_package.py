from PySide6.QtWidgets import QMessageBox

from hexrdgui.hexrd_config import HexrdConfig


def ask_to_create_physics_package_if_missing() -> bool:
    if HexrdConfig().has_physics_package:
        return True

    msg = 'This operation requires a physics package. ' 'Would you like to create one?'
    if QMessageBox.question(None, 'HEXRD', msg) == QMessageBox.Yes:
        HexrdConfig().create_default_physics_package()
        return True

    return False


def make_physics_package_from_old_overlay_config(overlay_config: list[dict]):
    # This function is only present for backward-compatibility with older
    # state files.
    # In the past, settings such as the sample layer and window thickness
    # were set individually on each overlay, and did not have global settings
    # stored in the physics package. If we load a state file that was set
    # up this way, we'll read some of the settings and set up the physics
    # package accordingly.
    if HexrdConfig().has_physics_package:
        return

    HexrdConfig().create_default_physics_package()
    physics = HexrdConfig().physics_package

    for overlay_dict in overlay_config:
        distortion_type = overlay_dict.get('tth_distortion_type')
        if not distortion_type:
            continue

        # In the older state files, layer distortion was always called
        # "SampleLayerDistortion"
        settings = overlay_dict.get('tth_distortion_kwargs', {})
        if distortion_type == 'SampleLayerDistortion':
            if settings.get('layer_thickness'):
                physics.sample_thickness = settings.get('layer_thickness') * 1e3
            if settings.get('layer_standoff'):
                physics.window_thickness = settings.get('layer_standoff') * 1e3
            if settings.get('pinhole_thickness'):
                physics.pinhole_thickness = settings['pinhole_thickness'] * 1e3
        else:
            # Assume it contains pinhole settings (Rygg or JHE)
            if settings.get('pinhole_radius'):
                physics.pinhole_radius = settings['pinhole_radius'] * 1e3
            if settings.get('pinhole_diameter'):
                physics.pinhole_diameter = settings['pinhole_diameter'] * 1e3
            if settings.get('pinhole_thickness'):
                physics.pinhole_thickness = settings['pinhole_thickness'] * 1e3
