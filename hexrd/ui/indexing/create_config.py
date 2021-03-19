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
    available_materials = list(HexrdConfig().materials.keys())
    selected_material = indexing_config.get('_selected_material')

    if selected_material not in available_materials:
        raise Exception(f'Selected material {selected_material} not available')

    material = HexrdConfig().material(selected_material)

    omaps = indexing_config['find_orientations']['orientation_maps']
    omaps['active_hkls'] = list(range(len(material.planeData.getHKLs())))

    # Set the active material on the config
    tmp = indexing_config.setdefault('material', {})
    tmp['active'] = material.name

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

    # Use unaggregated images if possible
    ims_dict = ImageLoadManager().unaggregated_images
    if ims_dict is None:
        # This probably means the image series was never aggregated.
        # Try using the imageseries dict.
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
