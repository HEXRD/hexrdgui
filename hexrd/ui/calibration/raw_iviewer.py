from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.overlays import PowderLineOverlay


def raw_iviewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = 'images'
        self.instr = create_hedm_instrument()

        # Callers should set this to indicate the detectors for which they
        # would like to generate ring data
        self.detectors = []

    def clear_rings(self):
        self.ring_data = {}

    def add_rings(self):
        self.clear_rings()

        if not HexrdConfig().show_overlays or not self.detectors:
            # Nothing to do
            return self.ring_data

        for mat_name in HexrdConfig().visible_material_names:
            mat = HexrdConfig().material(mat_name)
            self.ring_data[mat_name] = {}

            if not mat:
                # Print a warning, as this shouldn't happen
                print('Warning in InstrumentViewer.add_rings():',
                      mat_name, 'is not a valid material')
                continue

            overlay = PowderLineOverlay(mat.planeData, self.instr)
            self.ring_data[mat_name] = overlay.overlay('raw')

        return self.ring_data
