from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig


def raw_iviewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = 'images'
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

            kwargs = {
                'plane_data': mat.planeData,
                'instr': self.instr
            }
            if overlay['type'] == 'laue':
                # Modify kwargs here
                pass

            generator = overlay['generator'](**kwargs)
            overlay['data'] = generator.overlay('raw')
