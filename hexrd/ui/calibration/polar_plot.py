import numpy as np
import warnings

from hexrd import instrument
from .polarview import PolarView

from skimage.exposure import rescale_intensity
from skimage.exposure import equalize_adapthist

from .display_plane import DisplayPlane

from hexrd.ui.hexrd_config import HexrdConfig

snip_width = 9

tth_min = 1.
tth_max = 20.


def polar_viewer():
    iconfig = HexrdConfig().instrument_config
    images_dict = HexrdConfig().current_images_dict()
    plane_data = HexrdConfig().active_material.planeData

    return InstrumentViewer(iconfig, images_dict, plane_data)


def log_scale_img(img):
    img = np.array(img, dtype=float) - np.min(img) + 1.
    return np.log(img)


def load_instrument(config):
    rme = HexrdConfig().rotation_matrix_euler()
    return instrument.HEDMInstrument(instrument_config=config,
                                     tilt_calibration_mapping=rme)


class InstrumentViewer:

    def __init__(self, config, images_dict, plane_data):
        self.type = 'polar'
        self.plane_data = plane_data
        self.instr = load_instrument(config)
        self._load_panels()
        self._load_images(images_dict)
        self.dplane = DisplayPlane()

        # Resolution settings
        # As far as I can tell, self.pixel_size won't actually change
        # anything for a polar plot, so just hard-code it.
        self.pixel_size = 0.5
        self.pv_pixel_size = (
            HexrdConfig().polar_pixel_size_tth,
            HexrdConfig().polar_pixel_size_eta
        )

        self._make_dpanel()
        self.snip_width_init = 9
        self.snip_width = self.snip_width_init*self.pv_pixel_size[0]

        self.generate_image()

    def _load_panels(self):
        self.panels = list(self.instr._detectors.values())

    def _load_images(self, images_dict):
        # Make sure image keys and detector keys match
        if images_dict.keys() != self.instr._detectors.keys():
            msg = ('Images do not match the panel ids!\n' +
                   'Images: ' + str(list(images_dict.keys())) + '\n' +
                   'PanelIds: ' + str(list(self.instr._detectors.keys())))
            raise Exception(msg)

        self.images_dict = images_dict

    def _make_dpanel(self):
        self.dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(self.dpanel_sizes,
                                                self.pixel_size)

    # ========== Drawing
    def draw_polar(self, snip_width=snip_width):
        """show polar view of rings"""
        pv = PolarView([tth_min, tth_max], self.instr,
                       eta_min=-180., eta_max=180.,
                       pixel_size=self.pv_pixel_size)
        wimg = pv.warp_image(self.images_dict)
        self._angular_coords = pv.angular_grid
        self._extent = [tth_min, tth_max, 180., -180.]   # l, r, b, t
        self.plot_dplane(warped=wimg, snip_width=snip_width)

    def generate_image(self, **kwargs):
        if 'snip_width' in kwargs:
            self.draw_polar(snip_width=kwargs['snip_width'])
        else:
            self.draw_polar()
        self.add_rings()

    def clear_rings(self):
        self.ring_data = []
        self.rbnd_data = []

    def add_rings(self):
        self.clear_rings()
        if not HexrdConfig().show_rings:
            # We are not supposed to add rings
            return self.ring_data

        dp = self.dpanel

        selected_rings = HexrdConfig().selected_rings
        if selected_rings:
            # We should only get specific values
            tth_list = self.plane_data.getTTh()
            tth_list = [tth_list[i] for i in selected_rings]
            delta_tth = np.degrees(self.plane_data.tThWidth)

            ring_angs, ring_xys = dp.make_powder_rings(
                tth_list, delta_tth=delta_tth, delta_eta=1)
        else:
            ring_angs, ring_xys = dp.make_powder_rings(
                self.plane_data, delta_eta=1)

            tth_list = self.plane_data.getTTh()

        for tth in np.degrees(tth_list):
            self.ring_data.append(np.array([[-180, tth], [180, tth]]))

        if HexrdConfig().show_ring_ranges:
            tthw = HexrdConfig().ring_ranges
            if tthw is None:
                tthw = 0.5*np.degrees(self.plane_data.tThWidth)

            for tth in np.degrees(tth_list):
                self.rbnd_data.append(np.array([[-180, tth - tthw],
                                                [180, tth - tthw]]))
                self.rbnd_data.append(np.array([[-180, tth + tthw],
                                                [180, tth + tthw]]))

        return self.ring_data

    def plot_dplane(self, warped, snip_width=None):
        img = rescale_intensity(warped, out_range=(0., 1.))
        img = log_scale_img(log_scale_img(img))

        # plotting
        self.warped_image = warped

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            img = equalize_adapthist(img, clip_limit=0.1, nbins=2**16)

        # Rescale the data to match the scale of the original dataset
        # TODO: try to get the function to not rescale the
        # result to be between 0 and 1 in the first place so this will
        # not be necessary.
        images = self.images_dict.values()
        minimum = min([x.min() for x in images])
        maximum = max([x.max() for x in images])
        self.img = np.interp(img, (img.min(), img.max()), (minimum, maximum))
