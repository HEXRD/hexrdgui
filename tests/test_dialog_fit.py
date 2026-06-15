"""Tests for window/screen fitting in hexrdgui.utils.dialog.

The eta-omega map viewer (and other large dialogs) can open larger than the
display, leaving the title bar/edges off-screen and unreachable on window
managers that don't auto-clamp (Linux/X11, NoMachine). macOS clamps windows
itself, so that failure mode is not reproducible there; these tests exercise
the platform-independent clamping math directly with a fabricated screen.
"""

from PySide6.QtCore import QPoint, QRect, QSize

from hexrdgui.utils.dialog import fit_geometry_to_available


# A typical small/remote screen, with no decoration on the geometry by
# default (frame == geom) unless a test overrides it.
AVAILABLE = QRect(0, 0, 1280, 720)


def _fit(geom, available=AVAILABLE, frame=None, margin=0):
    # By default the frame equals the geometry (no decorations).
    if frame is None:
        frame = QRect(geom)
    return fit_geometry_to_available(geom, frame, available, margin)


def test_oversized_window_is_shrunk_to_available():
    # Window far larger than the screen (the #2026 scenario: 4000x3000).
    size, pos = _fit(QRect(0, 0, 4000, 3000))
    assert size == QSize(1280, 720)
    assert pos == QPoint(0, 0)


def test_window_within_screen_is_unchanged():
    geom = QRect(100, 50, 800, 600)
    size, pos = _fit(geom)
    assert size == QSize(800, 600)
    # Fully on-screen already -> left where it is.
    assert pos == QPoint(100, 50)


def test_offscreen_window_is_moved_back_on_screen():
    # On-screen-sized but positioned with its top-left off the bottom-right.
    geom = QRect(1200, 700, 400, 300)
    size, pos = _fit(geom)
    assert size == QSize(400, 300)
    # Clamped so the whole frame fits: x = 1280-400, y = 720-300.
    assert pos == QPoint(880, 420)
    assert AVAILABLE.contains(QRect(pos, size))


def test_decorations_are_accounted_for():
    # Window content exactly fills the screen, but a 10px border + 30px title
    # bar means the *frame* would overflow. It must be shrunk to leave room.
    geom = QRect(0, 0, 1280, 720)
    frame = QRect(-10, -30, 1280 + 20, 720 + 40)  # 10px sides, 30px top
    size, pos = _fit(geom, frame=frame)
    assert size == QSize(1280 - 20, 720 - 40)  # 1260 x 680
    # Frame top-left clamped to the available origin.
    assert pos == QPoint(0, 0)


def test_margin_leaves_breathing_room():
    size, _ = _fit(QRect(0, 0, 4000, 3000), margin=20)
    assert size == QSize(1260, 700)


def test_non_origin_screen_offset():
    # Multi-monitor: available screen does not start at (0, 0).
    available = QRect(1920, 0, 1280, 720)
    size, pos = _fit(QRect(0, 0, 4000, 3000), available=available)
    assert size == QSize(1280, 720)
    assert pos == QPoint(1920, 0)
    assert available.contains(QRect(pos, size))
