from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from matplotlib.backend_bases import MouseEvent

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.ui_loader import UiLoader
from hexrdgui.zoom_canvas import ZoomCanvas

if TYPE_CHECKING:
    from hexrdgui.image_canvas import ImageCanvas


class ZoomCanvasDialog:
    def __init__(
        self,
        main_canvas: ImageCanvas,
        draw_crosshairs: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('zoom_canvas_dialog.ui', parent)

        display_sums_in_subplots = self.ui.display_sums_in_subplots.isChecked()

        self.zoom_canvas = ZoomCanvas(
            main_canvas, draw_crosshairs, display_sums_in_subplots
        )
        self.ui.zoom_canvas_layout.addWidget(self.zoom_canvas)
        self.zoom_dimensions_changed(rerender=False)

        self.move_dialog_to_left()

        self.setup_connections()

    def setup_connections(self) -> None:
        self.ui.zoom_width.valueChanged.connect(self.zoom_dimensions_changed)
        self.ui.zoom_height.valueChanged.connect(self.zoom_dimensions_changed)
        self.ui.display_sums_in_subplots.toggled.connect(
            self.on_display_sums_in_subplots_toggled
        )
        self.ui.finished.connect(self.on_finished)

        self.bpe_id: int | None = self.main_canvas.mpl_connect(
            'button_press_event', self.on_button_pressed  # type: ignore[arg-type]
        )

    def show(self) -> None:
        self.set_focus_mode(True)
        self.ui.show()

    def on_finished(self) -> None:
        self.set_focus_mode(False)

        if self.bpe_id is not None:
            self.main_canvas.mpl_disconnect(self.bpe_id)
            self.bpe_id = None

        self.zoom_canvas.cleanup()

        # This must get deleted or the connections will stick around
        self.zoom_canvas.deleteLater()

    def set_focus_mode(self, b: bool) -> None:
        # This will disable some widgets in the GUI during focus mode
        # Be very careful to make sure focus mode won't be set permanently
        # if an exception occurs, or else this will ruin the user's session.
        # Therefore, this should only be turned on during important moments,
        # such as when a dialog is showing, and turned off during processing.
        HexrdConfig().enable_canvas_focus_mode.emit(b)

    def on_button_pressed(self, event: MouseEvent) -> None:
        if event.button != 1:
            # Ignore everything except left-click
            return

        self.toggle_frozen()

        # Switch over to this axis, in case we weren't there already.
        self.zoom_canvas.on_axes_entered(event)

    def toggle_frozen(self) -> None:
        self.zoom_canvas.frozen = not self.zoom_canvas.frozen

    def zoom_dimensions_changed(self, rerender: bool = True) -> None:
        self.zoom_canvas.zoom_width = self.zoom_width
        self.zoom_canvas.zoom_height = self.zoom_height

        if rerender:
            self.zoom_canvas.render()

        if self.zoom_canvas.frozen:
            # Make sure the main canvas gets rerendered so that the duplicate
            # box lines get cleared.
            self.main_canvas.draw()

    def on_display_sums_in_subplots_toggled(self, b: bool) -> None:
        self.zoom_canvas.display_sums_in_subplots = b

    @property
    def zoom_width(self) -> int:
        return self.ui.zoom_width.value()

    @zoom_width.setter
    def zoom_width(self, v: int) -> None:
        self.ui.zoom_width.setValue(v)

    @property
    def zoom_height(self) -> int:
        return self.ui.zoom_height.value()

    @zoom_height.setter
    def zoom_height(self, v: int) -> None:
        self.ui.zoom_height.setValue(v)

    @property
    def main_canvas(self) -> ImageCanvas:
        return self.zoom_canvas.main_canvas

    def move_dialog_to_left(self) -> None:
        if not self.ui.parent():
            return

        # This moves the dialog to the left border of the parent
        ph = self.ui.parent().geometry().height()
        px = self.ui.parent().geometry().x()
        py = self.ui.parent().geometry().y()
        dw = self.ui.width()
        dh = self.ui.height()
        self.ui.setGeometry(px, py + (ph - dh) / 2.0, dw, dh)
