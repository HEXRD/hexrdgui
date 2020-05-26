import numpy as np

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig


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

    def generate_rings(self, plane_data, detector):
        rings = []
        rbnds = []
        rbnd_indices = []

        # If there are no rings, there is nothing to do
        if not HexrdConfig().show_overlays or len(plane_data.getTTh()) == 0:
            return rings, rbnds, rbnd_indices

        # A delta_tth is needed here, even if the plane data tThWidth
        # is None. Default to 0.125 degrees if tThWidth is None.
        # I don't see a difference in the output if different values for
        # delta_tth are chosen here, when plane_data.tThWidth is None.
        if plane_data.tThWidth:
            delta_tth = np.degrees(plane_data.tThWidth)
        else:
            delta_tth = 0.125
        ring_angs, ring_xys = detector.make_powder_rings(
            plane_data, delta_tth=delta_tth, delta_eta=1)

        for ring in ring_xys:
            rings.append(detector.cartToPixel(ring))

        if plane_data.tThWidth is not None:
            delta_tth = np.degrees(plane_data.tThWidth)
            indices, ranges = plane_data.getMergedRanges()

            r_lower = [r[0] for r in ranges]
            r_upper = [r[1] for r in ranges]
            l_angs, l_xyz = detector.make_powder_rings(
                r_lower, delta_tth=delta_tth, delta_eta=1)
            u_angs, u_xyz = detector.make_powder_rings(
                r_upper, delta_tth=delta_tth, delta_eta=1)
            for l, u in zip(l_xyz, u_xyz):
                rbnds.append(detector.cartToPixel(l))
                rbnds.append(detector.cartToPixel(u))
            for ind in indices:
                rbnd_indices.append(ind)
                rbnd_indices.append(ind)

        return rings, rbnds, rbnd_indices

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

            for det_name in self.detectors:
                if det_name not in self.instr.detectors:
                    # Print a warning, as this shouldn't happen
                    print('Warning in InstrumentViewer.add_rings():',
                          det_name, 'is not a valid detector')
                    continue

                detector = self.instr.detectors[det_name]
                rings, rbnds, rbnd_indices = self.generate_rings(mat.planeData,
                                                                 detector)
                self.ring_data[mat_name][det_name] = {
                    'ring_data': rings,
                    'rbnd_data': rbnds,
                    'rbnd_indices': rbnd_indices
                }

        return self.ring_data
