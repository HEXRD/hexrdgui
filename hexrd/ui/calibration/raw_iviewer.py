from hexrd.ui.constants import UI_RAW
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import overlay_generator


def raw_iviewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = UI_RAW
        self.instr = create_hedm_instrument()

    def update_overlay_data(self):
        HexrdConfig().clear_overlay_data()

        if not HexrdConfig().show_overlays:
            # Nothing to do
            return

        for overlay in HexrdConfig().overlays:
            if not overlay['visible']:
                # Skip over invisible overlays
                continue

            mat_name = overlay['material']
            mat = HexrdConfig().material(mat_name)

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.update_overlay_data():',
                      f'{mat_name} is not a valid material')
                continue

            type = overlay['type']
            kwargs = {
                'plane_data': mat.planeData,
                'instr': self.instr
            }
            # Add any options
            kwargs.update(overlay.get('options', {}))

            generator = overlay_generator(type)(**kwargs)
            overlay['data'] = generator.overlay(UI_RAW)
