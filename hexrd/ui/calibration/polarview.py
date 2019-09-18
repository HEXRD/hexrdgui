import numpy as np

from skimage.exposure import rescale_intensity

from hexrd.transforms.xfcapi import \
     anglesToGVec, \
     gvecToDetectorXY

from hexrd import constants as cnst

from hexrd.ui.hexrd_config import HexrdConfig

tvec_c = cnst.zeros_3


def log_scale_img(img):
    img = np.array(img, dtype=float) - np.min(img) + 1.
    return np.log(img)


class PolarView(object):
    """Create (two-theta, eta) plot of detectors
    """
    def __init__(self, instrument, eta_min=0., eta_max=360.):

        # etas
        self._eta_min = np.radians(eta_min)
        self._eta_max = np.radians(eta_max)

        self.instr = instrument

        self.images_dict = HexrdConfig().current_images_dict()

        self.warp_dict = {}

    @property
    def detectors(self):
        return self.instr.detectors

    @property
    def tvec_s(self):
        return self.instr.tvec

    @property
    def tth_min(self):
        return np.radians(HexrdConfig().polar_res_tth_min)

    @property
    def tth_max(self):
        return np.radians(HexrdConfig().polar_res_tth_max)

    @property
    def tth_range(self):
        return self.tth_max - self.tth_min

    @property
    def tth_pixel_size(self):
        return HexrdConfig().polar_pixel_size_tth

    @property
    def eta_min(self):
        return self._eta_min

    @property
    def eta_max(self):
        return self._eta_max

    @property
    def eta_range(self):
        return self.eta_max - self.eta_min

    @property
    def eta_pixel_size(self):
        return HexrdConfig().polar_pixel_size_eta

    @property
    def ntth(self):
        return int(np.ceil(np.degrees(self.tth_range) / self.tth_pixel_size))

    @property
    def neta(self):
        return int(np.ceil(np.degrees(self.eta_range) / self.eta_pixel_size))

    @property
    def shape(self):
        return (self.neta, self.ntth)

    @property
    def angular_grid(self):
        tth_vec = np.radians(self.tth_pixel_size * (np.arange(self.ntth)))\
            + self.tth_min + 0.5 * np.radians(self.tth_pixel_size)
        eta_vec = np.radians(self.eta_pixel_size * (np.arange(self.neta)))\
            + self.eta_min + 0.5 * np.radians(self.eta_pixel_size)
        return np.meshgrid(eta_vec, tth_vec, indexing='ij')

    def create_warp_image(self, det):
        angpts = self.angular_grid
        dummy_ome = np.zeros((self.ntth * self.neta))

        # lcount = 0
        panel = self.detectors[det]
        img = self.images_dict[det]

        if HexrdConfig().show_detector_borders:
            # Draw a border around the detector panel
            max_int = np.percentile(img, 99.95)
            # A large percentage such as 3% is needed for it to show up
            pbuf = int(0.03 * np.mean(img.shape))
            img[:, :pbuf] = max_int
            img[:, -pbuf:] = max_int
            img[:pbuf, :] = max_int
            img[-pbuf:, :] = max_int

        gpts = anglesToGVec(
            np.vstack([
                angpts[1].flatten(),
                angpts[0].flatten(),
                dummy_ome,
                ]).T, bHat_l=panel.bvec)
        xypts = gvecToDetectorXY(
            gpts,
            panel.rmat, np.eye(3), np.eye(3),
            panel.tvec, self.tvec_s, tvec_c,
            beamVec=panel.bvec)
        if panel.distortion is not None:
            dfunc = panel.distortion[0]
            dparams = panel.distortion[1]
            xypts = dfunc(xypts, dparams)

        self.warp_dict[det] = panel.interpolate_bilinear(
            xypts, img, pad_with_nans=False).reshape(self.shape)
        return self.warp_dict[det]

    def generate_image(self):
        img = np.zeros(self.shape)
        for key in self.images_dict.keys():
            img += self.warp_dict[key]

        img = rescale_intensity(img, out_range=(0., 1.))
        img = log_scale_img(log_scale_img(img))

        # Rescale the data to match the scale of the original dataset
        # TODO: try to get create_calibration_image to not rescale the
        # result to be between 0 and 1 in the first place so this will
        # not be necessary.
        self.img = np.interp(img, (img.min(), img.max()), (self.min, self.max))

    def warp_all_images(self):
        # Cache the image max and min for later use
        images = self.images_dict.values()
        self.min = min([x.min() for x in images])
        self.max = max([x.max() for x in images])

        # Create the warped image for each detector
        for det in self.images_dict.keys():
            self.create_warp_image(det)

        # Generate the final image
        self.generate_image()

    def update_detector(self, det):
        t_conf = HexrdConfig().get_detector(det)['transform']
        self.instr.detectors[det].tvec = t_conf['translation']['value']
        self.instr.detectors[det].tilt = t_conf['tilt']['value']

        # Update the individual detector image
        self.create_warp_image(det)

        # Generate the final image
        self.generate_image()
