"""HexrdConfig and ImageLoadManager live for the whole process.

That makes two things easy to get wrong: what they hand out to background
threads while the main thread mutates it, and what they keep alive.
"""

import threading
import time
import weakref

import numpy as np

from PySide6.QtWidgets import QWidget

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.image_load_manager import ImageLoadManager


class DummyImageSeries(list):
    def __getitem__(self, idx):
        # A real imageseries decompresses/reads here, releasing the GIL.
        # That is the window a concurrent swap slips into.
        time.sleep(0)
        return super().__getitem__(idx)


def test_image_accessors_survive_a_concurrent_swap(qtbot):
    # The view generation reads these from its worker thread, while loading
    # images clears `imageseries_dict` and refills it one detector at a time.
    config = HexrdConfig()
    original = dict(config.imageseries_dict)
    entries = {f'det_{i}': DummyImageSeries([np.zeros((4, 4))]) for i in range(16)}
    stop = threading.Event()

    def swap():
        while not stop.is_set():
            config.imageseries_dict.clear()
            config.imageseries_dict.update(entries)

    thread = threading.Thread(target=swap, daemon=True)
    thread.start()
    try:
        for _ in range(500):
            # Neither may raise, and each must see a whole dict, not a
            # half-refilled one.
            assert len(config.raw_images_dict) in (0, len(entries))
            config.omega_imageseries_dict
    finally:
        stop.set()
        thread.join()
        config.imageseries_dict.clear()
        config.imageseries_dict.update(original)


def test_singletons_hold_widgets_weakly(qtbot):
    # A strong reference would pin a whole torn-down window for the rest of
    # the process, leaving Python wrappers over freed C++ objects behind.
    for singleton, attribute in (
        (ImageLoadManager(), 'ui_parent'),
        (HexrdConfig(), 'active_canvas'),
    ):
        previous = getattr(singleton, attribute)
        try:
            widget = QWidget()
            ref = weakref.ref(widget)
            setattr(singleton, attribute, widget)
            assert getattr(singleton, attribute) is widget

            del widget
            assert ref() is None, f'{attribute} kept the widget alive'
        finally:
            setattr(singleton, attribute, previous)
