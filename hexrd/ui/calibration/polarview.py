import numpy as np

from hexrd.xrd.transforms_CAPI import \
     anglesToGVec, \
     gvecToDetectorXY

from hexrd.xrd.crystallography import PlaneData

from hexrd import constants as cnst

tvec_c = cnst.zeros_3


class PolarView(object):
    """Create (two-theta, eta) plot of detectors
    """
    def __init__(self, plane_data, instrument,
                 eta_min=0., eta_max=360.,
                 pixel_size=(0.1, 0.25)):
        # tth stuff
        if isinstance(plane_data, PlaneData):
            tth_ranges = plane_data.getTThRanges()
            self._tth_min = np.min(tth_ranges)
            self._tth_max = np.max(tth_ranges)
        else:
            self._tth_min = np.radians(plane_data[0])
            self._tth_max = np.radians(plane_data[1])

        # etas
        self._eta_min = np.radians(eta_min)
        self._eta_max = np.radians(eta_max)

        self._tth_pixel_size = pixel_size[0]
        self._eta_pixel_size = pixel_size[1]

        self._detectors = instrument.detectors
        self._tvec_s = instrument.tvec

    @property
    def detectors(self):
        return self._detectors

    @property
    def tvec_s(self):
        return self._tvec_s

    @property
    def tth_min(self):
        return self._tth_min

    @tth_min.setter
    def tth_min(self, x):
        assert x < self.tth_max,\
          'tth_min must be < tth_max (%f)' % (self._tth_max)
        self._tth_min = x

    @property
    def tth_max(self):
        return self._tth_max

    @tth_max.setter
    def tth_max(self, x):
        assert x > self.tth_min,\
          'tth_max must be < tth_min (%f)' % (self._tth_min)
        self._tth_max = x

    @property
    def tth_range(self):
        return self.tth_max - self.tth_min

    @property
    def tth_pixel_size(self):
        return self._tth_pixel_size

    @tth_pixel_size.setter
    def tth_pixel_size(self, x):
        self._tth_pixel_size = float(x)

    @property
    def eta_min(self):
        return self._eta_min

    @eta_min.setter
    def eta_min(self, x):
        assert x < self.eta_max,\
          'eta_min must be < eta_max (%f)' % (self.eta_max)
        self._eta_min = x

    @property
    def eta_max(self):
        return self._eta_max

    @eta_max.setter
    def eta_max(self, x):
        assert x > self.eta_min,\
          'eta_max must be < eta_min (%f)' % (self.eta_min)
        self._eta_max = x

    @property
    def eta_range(self):
        return self.eta_max - self.eta_min

    @property
    def eta_pixel_size(self):
        return self._eta_pixel_size

    @eta_pixel_size.setter
    def eta_pixel_size(self, x):
        self._eta_pixel_size = float(x)

    @property
    def ntth(self):
        return int(np.ceil(np.degrees(self.tth_range)/self.tth_pixel_size))

    @property
    def neta(self):
        return int(np.ceil(np.degrees(self.eta_range)/self.eta_pixel_size))

    @property
    def shape(self):
        return (self.neta, self.ntth)

    @property
    def angular_grid(self):
        tth_vec = np.radians(self.tth_pixel_size*(np.arange(self.ntth)))\
            + self.tth_min + 0.5*np.radians(self.tth_pixel_size)
        eta_vec = np.radians(self.eta_pixel_size*(np.arange(self.neta)))\
            + self.eta_min + 0.5*np.radians(self.eta_pixel_size)
        return np.meshgrid(eta_vec, tth_vec, indexing='ij')

    # =========================================================================
    #                         ####### METHODS #######
    # =========================================================================
    def warp_image(self, image_dict):
        """
        gvecToDetectorXY(gVec_c,
                         rMat_d, rMat_s, rMat_c,
                         tVec_d, tVec_s, tVec_c,
                         beamVec=array([[-0.], [-0.], [-1.]]))
        """
        angpts = self.angular_grid
        dummy_ome = np.zeros((self.ntth*self.neta))

        # lcount = 0
        wimg = np.zeros(self.shape)
        for detector_id in self.detectors:
            panel = self.detectors[detector_id]
            img = image_dict[detector_id]
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

            wimg += panel.interpolate_bilinear(
                xypts, img,
                pad_with_nans=False).reshape(self.shape)
        return wimg

    def tth_to_pixel(self, tth):
        """
        convert two-theta value to pixel value (float) along two-theta axis
        """
        return np.degrees(tth - self.tth_min)/self.tth_pixel_size
