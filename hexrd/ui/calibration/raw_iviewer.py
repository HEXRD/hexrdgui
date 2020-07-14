from hexrd.ui.constants import UI_RAW
from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.overlays import update_overlay_data


def raw_iviewer():
    return InstrumentViewer()


class InstrumentViewer:

    def __init__(self):
        self.type = UI_RAW
        self.instr = create_hedm_instrument()

    def update_overlay_data(self):
        update_overlay_data(self.instr, self.type)
