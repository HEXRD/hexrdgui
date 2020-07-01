import copy

from hexrd.config.root import RootConfig
from hexrd.config.material import MaterialConfig
from hexrd.config.instrument import Instrument as InstrumentConfig
from hexrd.imageseries.omega import OmegaImageSeries

from hexrd.ui.create_hedm_instrument import create_hedm_instrument
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.image_load_manager import ImageLoadManager


def create_indexing_config():
    # Creates a hexrd.config class from the indexing configuration

    # Make a copy to modify
    indexing_config = copy.deepcopy(HexrdConfig().indexing_config)
    material = HexrdConfig().active_material
    omaps = indexing_config['find_orientations']['orientation_maps']
    omaps['active_hkls'] = active_hkl_indices(material.planeData)

    # Set the active material on the config
    tmp = indexing_config.setdefault('material', {})
    tmp['active'] = HexrdConfig().active_material_name

    # Create the root config from the indexing config dict
    config = RootConfig(indexing_config)

    # Create and set instrument config
    iconfig = InstrumentConfig()
    iconfig._hedm = create_hedm_instrument()
    config.instrument = iconfig

    # Create and set material config
    mconfig = MaterialConfig(config)
    mconfig.materials = HexrdConfig().materials
    config.material = mconfig

    # Set the image series dict
    ims_dict = HexrdConfig().imageseries_dict
    # Load omega data if it is missing
    load_omegas_dict = {
        k: ims for k, ims in ims_dict.items() if 'omega' not in ims.metadata
    }
    if load_omegas_dict:
        ImageLoadManager().add_omega_metadata(load_omegas_dict)

    # Convert image series into OmegaImageSeries
    for key, ims in ims_dict.items():
        ims_dict[key] = OmegaImageSeries(ims)

    config.image_series = ims_dict

    return config


def active_hkl_indices(plane_data):
    # Return a list of active indices, taking into account exclusions and
    # tTh limitations.

    # These need to be lists, or the `in` operator won't work properly
    hkls = plane_data.getHKLs().tolist()
    full_hkl_list = [x['hkl'].tolist() for x in plane_data.hklDataList]

    def hkl_is_active(i):
        return full_hkl_list[i] in hkls

    return [i for i in range(len(full_hkl_list)) if hkl_is_active(i)]
