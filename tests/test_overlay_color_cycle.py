"""Tests for cycling distinct colors across newly-created powder overlays."""

from typing import Generator

import pytest

from PySide6.QtWidgets import QApplication

from hexrd.material import Material

from hexrdgui.constants import OverlayType
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays import POWDER_OVERLAY_COLOR_CYCLE
from hexrdgui.overlays.powder_overlay import PowderOverlay


MATERIAL_NAME = 'color_cycle_test_material'


@pytest.fixture
def config(qapp: QApplication) -> Generator[HexrdConfig, None, None]:
    # HexrdConfig is a singleton that requires a QApplication (qapp).
    cfg = HexrdConfig()
    cfg.add_material(MATERIAL_NAME, Material())
    saved_overlays = list(cfg.overlays)
    cfg.overlays.clear()
    try:
        yield cfg
    finally:
        cfg.overlays.clear()
        cfg.overlays.extend(saved_overlays)
        cfg.remove_material(MATERIAL_NAME)


def color_pair(overlay: PowderOverlay) -> tuple[str, str]:
    return (overlay.style['data']['c'], overlay.style['ranges']['c'])


def test_new_overlays_get_distinct_pairs(config: HexrdConfig) -> None:
    for _ in range(3):
        config.append_overlay(MATERIAL_NAME, OverlayType.powder)

    pairs = [color_pair(o) for o in config.overlays]
    assert pairs == POWDER_OVERLAY_COLOR_CYCLE[:3]
    assert len(set(pairs)) == 3


def test_least_used_pair_reused_after_removal(config: HexrdConfig) -> None:
    config.append_overlay(MATERIAL_NAME, OverlayType.powder)  # pair 0
    config.append_overlay(MATERIAL_NAME, OverlayType.powder)  # pair 1
    config.overlays.pop(0)  # free up pair 0
    config.append_overlay(MATERIAL_NAME, OverlayType.powder)

    # The freed pair should be reused rather than picking a third color.
    assert color_pair(config.overlays[-1]) == POWDER_OVERLAY_COLOR_CYCLE[0]
