import numpy as np

from hexrd import instrument
from .polarview import PolarView

from skimage.exposure import rescale_intensity

from .display_plane import DisplayPlane

from hexrd.ui.hexrd_config import HexrdConfig

snip_width = 9

tth_min = 1.
tth_max = 20.

default_options = {
    'polarview': {
        'tth-pixel-size': 0.05,
        'eta-pixel-size': 0.2
    },
    'do_erosion': False
}
tth_pixel_size = default_options['polarview']['tth-pixel-size']
default_options['snip_width'] = int(np.ceil(2.0 / tth_pixel_size))


def polar_image():
    iconfig = HexrdConfig().iconfig
    images_dict = HexrdConfig().images()
    plane_data = HexrdConfig().active_material.planeData

    iviewer = InstrumentViewer(iconfig, images_dict, plane_data)

    # Rescale the data to match the scale of the original dataset
    # TODO: try to get create_calibration_image to not rescale the
    # result to be between 0 and 1 in the first place so this will
    # not be necessary.
    images = images_dict.values()
    minimum = min([x.min() for x in images])
    maximum = max([x.max() for x in images])
    img = iviewer.image
    img = np.interp(img, (img.min(), img.max()), (minimum, maximum))

    return img, iviewer._extent, iviewer.ring_data, iviewer.rbnd_data


def log_scale_img(img):
    img = np.array(img, dtype=float) - np.min(img) + 1.
    return np.log(img)


def load_instrument(config):
    return instrument.HEDMInstrument(instrument_config=config)


class InstrumentViewer:

    def __init__(self, config, image_dict, plane_data, opts=default_options):
        self.plane_data = plane_data
        self.instr = load_instrument(config)
        self._load_panels()
        self._load_images(image_dict)
        self._load_opts(opts)
        self.dplane = DisplayPlane()
        self.pixel_size = 0.5
        self._make_dpanel()

        self.image = None
        self.generate_image()

    # ========== Set up
    def _load_opts(self, d):
        pview = d['polarview']
        self.opts = d
        self.pv_pixel_size = (pview['tth-pixel-size'],
                              pview['eta-pixel-size'])
        if 'snip_width' in d:
            self.snip_width_init = d['snip_width']
        else:
            self.snip_width_init = 9
        self.snip_width = self.snip_width_init*self.pv_pixel_size[0]

        if 'do_erosion' in d:
            self.do_erosion = np.bool(d['do_erosion'])

    def _load_panels(self):
        self.panels = list(self.instr._detectors.values())

    def _load_images(self, image_dict):
        # Make sure image keys and detector keys match
        if image_dict.keys() != self.instr._detectors.keys():
            msg = ('Images do not match the panel ids!\n' +
                   'Images: ' + str(list(image_dict.keys())) + '\n' +
                   'PanelIds: ' + str(list(self.instr._detectors.keys())))
            raise Exception(msg)

        self.image_dict = image_dict

    def _make_dpanel(self):
        self.dpanel_sizes = self.dplane.panel_size(self.instr)
        self.dpanel = self.dplane.display_panel(self.dpanel_sizes,
                                                self.pixel_size)

    # ========== Drawing
    def draw_polar(self, snip_width=None):
        """show polar view of rings"""
        pv = PolarView([tth_min, tth_max], self.instr,
                       eta_min=-180., eta_max=180.,
                       pixel_size=self.pv_pixel_size)
        wimg = pv.warp_image(self.image_dict)
        self._angular_coords = pv.angular_grid
        self._extent = [tth_min, tth_max, 180., -180.]   # l, r, b, t
        self.plot_dplane(warped=wimg, snip_width=snip_width)

    def generate_image(self, **kwargs):
        if 'snip_width' in kwargs:
            self.draw_polar(snip_width=kwargs['snip_width'])
        else:
            self.draw_polar()
        self.add_rings()

    def add_rings(self):
        self.ring_data = []
        self.rbnd_data = []

        if not HexrdConfig().show_rings:
            # We are not supposed to add rings
            return

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

    def plot_dplane(self, warped, snip_width=None):
        if snip_width is None:
            snip_width = self.opts['snip_width']

        img = rescale_intensity(warped, out_range=(0., 1.))
        img = log_scale_img(log_scale_img(img))

        # plotting
        self.warped_image = warped
        self.image = img
