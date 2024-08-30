import os
from pathlib import Path

import h5py
import numpy as np

from hexrd import imageseries
from hexrd.fitting.calibration import PowderCalibrator
from hexrd.imageseries.process import ProcessedImageSeries
from hexrd.instrument import HEDMInstrument
from hexrd.material import load_materials_hdf5


example_repo_path = Path(os.environ['HEXRD_EXAMPLE_REPO_PATH'])
ceria_examples_path = example_repo_path / 'eiger/first_ceria'
data_path = ceria_examples_path / 'ff_000_data_000001.h5'

with h5py.File(data_path, 'r') as rf:
    # Just return the first frame
    image_data = rf['/entry/data/data'][0]

instr_path = ceria_examples_path / 'eiger_ceria_uncalibrated_composite.hexrd'
with h5py.File(instr_path, 'r') as rf:
    instr = HEDMInstrument(rf)

materials_path = ceria_examples_path / 'ceria.h5'
all_materials = load_materials_hdf5(materials_path)
material = all_materials['CeO2']

# Break up the image data into separate images for each detector
# It's easiest to do this using hexrd's imageseries and
# ProcessedImageSeries
ims_dict = {}
ims = imageseries.open(None, format='array', data=image_data)
for det_key, panel in instr.detectors.items():
    ims_dict[det_key] = ProcessedImageSeries(
        ims, oplist=[('rectangle', panel.roi)]
    )

# Create the img_dict
img_dict = {k: v[0] for k, v in ims_dict.items()}

# Auto pick options
options = {
    'eta_tol': 1.0,
    'pk_type': 'gaussian',
    'bg_type': 'linear',
    # The fwhm (full-width half max) estimate is an initial guess
    # for the peak size. If `None`, the initial guess is "guessed"
    # automatically.
    'fwhm_estimate': None,
    # These next two are options passed to `autopick_points()`
    # These are the two that kick out "bunk fits"
    'fit_tth_tol': 0.1,
    'int_cutoff': 0.0001,
}

# Calibrator for calibrating the Ceria powder lines
kwargs = {
    'instr': instr,
    'material': material,
    'img_dict': img_dict,
    'eta_tol': options['eta_tol'],
    'fwhm_estimate': options['fwhm_estimate'],
    'pktype': options['pk_type'],
    'bgtype': options['bg_type'],
}

powder_calibrator = PowderCalibrator(**kwargs)

powder_calibrator.autopick_points(
    fit_tth_tol=options['fit_tth_tol'],
    int_cutoff=options['int_cutoff'],
)

# Get the results
results = powder_calibrator.calibration_picks

# This will require unpickling
np.save('premade_calibration_picks.npy', results)
