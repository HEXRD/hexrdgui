from PySide6.QtCore import QByteArray, QPoint, QRect, QSettings, QSize
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget


def fit_geometry_to_available(
    geom: QRect, frame: QRect, available: QRect, margin: int = 0
) -> tuple[QSize, QPoint]:
    """Pure geometry behind `fit_window_to_screen` (no live Qt window calls).

    Given a window's current geometry (decoration-exclusive), its frame
    geometry (decoration-inclusive), and the screen's available rect, return
    ``(size, frame_pos)``: the size to resize the window to and the position
    to move the window frame's top-left to, such that the whole frame fits
    inside ``available``. Kept side-effect-free so it can be unit tested with
    a fabricated screen rect on any platform.
    """
    # The difference between frame and geometry is the decoration thickness
    # (title bar, borders). Subtract it so the window plus its decorations
    # fits on-screen.
    decoration_w = frame.width() - geom.width()
    decoration_h = frame.height() - geom.height()

    max_w = max(available.width() - decoration_w - margin, 0)
    max_h = max(available.height() - decoration_h - margin, 0)
    size = geom.size().boundedTo(QSize(max_w, max_h))

    # Clamp the (decoration-inclusive) frame top-left so the whole frame -
    # and in particular the title bar - stays within the available area.
    frame_w = size.width() + decoration_w
    frame_h = size.height() + decoration_h
    x = min(max(frame.x(), available.x()), available.x() + available.width() - frame_w)
    y = min(max(frame.y(), available.y()), available.y() + available.height() - frame_h)
    return size, QPoint(x, y)


def fit_window_to_screen(window: QWidget, margin: int = 0) -> None:
    """Ensure a top-level window fits within the available screen area.

    Shrinks the window if it is larger than the screen's available
    geometry, and moves it so that the whole window frame (including the
    title bar and edges) stays on-screen. This prevents the window from
    opening larger than the display - on any small screen, and especially
    over remote desktops (VNC/RDP/NoMachine) - where its decorations would
    otherwise be off-screen and therefore impossible to grab to resize or
    move.

    Should be called after the window has been shown, so that the frame
    (decoration) geometry is known.
    """
    screen = window.screen() or QApplication.primaryScreen()
    if screen is None:
        return

    size, pos = fit_geometry_to_available(
        window.geometry(),
        window.frameGeometry(),
        screen.availableGeometry(),
        margin,
    )
    if size != window.size():
        window.resize(size)
    # window.move() positions the frame top-left for top-level windows.
    window.move(pos)


def save_window_geometry(window: QWidget, key: str) -> None:
    """Persist a window's size/position/state to QSettings under ``key``."""
    QSettings().setValue(key, window.saveGeometry())


def restore_window_geometry(window: QWidget, key: str) -> bool:
    """Restore a window's geometry previously saved with `save_window_geometry`.

    Returns True if a saved geometry was found and applied. Callers should still
    run `fit_window_to_screen` after the window is shown so a geometry saved on a
    larger display is clamped back onto the current screen.
    """
    data = QSettings().value(key)
    if isinstance(data, QByteArray) and not data.isEmpty():
        return bool(window.restoreGeometry(data))
    return False


def open_url(url: str) -> bool:
    # Open the specified URL in a web browser
    if not url.startswith('http'):
        # Assume that this is a relative path for the HEXRDGUI docs
        url = f'https://hexrdgui.readthedocs.io/en/latest/{url}'

    return QDesktopServices.openUrl(url)


def add_help_url(button_box: QDialogButtonBox, url: str) -> None:
    # This connects "helpRequested" from the button box with opening a URL.
    # If the button box doesn't have a "Help" button, one will be added
    # automatically.
    if button_box.button(QDialogButtonBox.StandardButton.Help) is None:
        # If it doesn't have a help button, then add one
        button_box.addButton(QDialogButtonBox.StandardButton.Help)

    button_box.helpRequested.connect(lambda: open_url(url))
