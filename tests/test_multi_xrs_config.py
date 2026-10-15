"""Instrument config paths for an instrument with multiple x-ray sources.

With more than one x-ray source, the beam name is an extra layer in every
`['beam', ...]` path, so prefix checks on those paths must account for it.
"""

import pytest

from hexrdgui.hexrd_config import HexrdConfig


@pytest.fixture
def multi_xrs_config(main_window, example_repo_path):
    config = HexrdConfig()
    path = example_repo_path / 'tardis/2xrs/tardis_2xrs_example.yml'
    config.load_instrument_config(str(path))
    assert config.has_multi_xrs
    return config


def test_multi_xrs_form_view(main_window, multi_xrs_config, qtbot):
    config = multi_xrs_config

    # The example has no energy correction, so the form view shows defaults
    assert config.active_beam.get('energy_correction') is None
    path = ['beam', 'energy_correction', 'intercept']
    assert config.get_instrument_config_val(path) == 0
    main_window.instrument_form_view_widget.update_gui_from_config()

    # Editing the active beam's vector must emit the matching signal
    path = ['beam', config.active_beam_name, 'vector', 'azimuth']
    old = config.get_instrument_config_val(path)
    with qtbot.waitSignal(config.beam_vector_changed, timeout=1000):
        config.set_instrument_config_val(path, old + 1)
    config.set_instrument_config_val(path, old)
