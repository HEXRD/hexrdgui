import numpy as np

from hexrd import instrument
from hexrd import imageseries
from .polarview import PolarView

from skimage.exposure import rescale_intensity

from .display_plane import DisplayPlane

Pimgs = imageseries.process.ProcessedImageSeries

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


def create_polar_calibration_image(config, images, plane_data):
    iviewer = InstrumentViewer(config, images, plane_data)

    # Rescale the data to match the scale of the original dataset
    # TODO: try to get create_calibration_image to not rescale the
    # result to be between 0 and 1 in the first place so this will
    # not be necessary.
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

    def __init__(self, config, imgs, plane_data, opts=default_options):
        self.plane_data = plane_data
        self.instr = load_instrument(config)
        self._load_panels()
        self._load_images(imgs)
        self._load_opts(opts)
        self.dplane = DisplayPlane()
        self.pixel_size = 0.5
        self._make_dpanel()

        self.image = None
        self.have_rings = False
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
        self.panel_ids = list(self.instr._detectors.keys())
        self.panels = list(self.instr._detectors.values())

    def _load_images(self, imgs):
        self.images = []
        self.image_dict = {}
        # Just assume for now they are already arranged correctly
        for img, pid in zip(imgs, self.panel_ids):
            self.images.append(img)
            self.image_dict[pid] = img

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
        tthw = 0.5*np.degrees(self.plane_data.tThWidth)
        if not self.have_rings:
            # generate and save rings
            dp = self.dpanel
            ring_angs, ring_xys = dp.make_powder_rings(
                self.plane_data, delta_eta=1)

            for tth in np.degrees(self.plane_data.getTTh()):
                self.ring_data.append(np.array([[-180, tth], [180, tth]]))
                self.rbnd_data.append(np.array([[-180, tth - tthw],
                                                [180, tth - tthw]]))
                self.rbnd_data.append(np.array([[-180, tth + tthw],
                                                [180, tth + tthw]]))
            self.have_rings = True

    def plot_dplane(self, warped, snip_width=None):
        if snip_width is None:
            snip_width = self.opts['snip_width']

        img = rescale_intensity(warped, out_range=(0., 1.))
        img = log_scale_img(log_scale_img(img))

        # plotting
        self.warped_image = warped
        self.image = img
