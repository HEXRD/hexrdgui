from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

if TYPE_CHECKING:
    import matplotlib as mpl
    from matplotlib.image import AxesImage

from hexrdgui.color_map_editor import ColorMapEditor
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader


class WppfSimulatedPolarDialog:
    def __init__(
        self,
        pv_bin: np.ndarray,
        pv_sim: np.ndarray | None,
        extent: list[float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        self.ui = UiLoader().load_file('wppf_simulated_polar_dialog.ui', parent)

        if pv_sim is None:
            pv_sim = np.zeros_like(pv_bin)

        self.pv_bin = pv_bin
        self.pv_sim = pv_sim
        self.extent = extent

        self.axes_images: list[AxesImage] = []

        self.cmap: str | mpl.colors.Colormap = HexrdConfig().default_cmap
        self.norm: mpl.colors.Normalize | None = None
        self.transform = lambda x: x

        self.setup_canvas()
        self.setup_color_map()

    def setup_color_map(self) -> None:
        self.color_map_editor = ColorMapEditor(self, self.ui)
        self.ui.color_map_editor_layout.addWidget(self.color_map_editor.ui)
        self.color_map_editor.update_bounds(unmasked(self.scaled_image_data))
        self.color_map_editor.data = self.data

    def setup_canvas(self) -> None:
        canvas = FigureCanvas(Figure(tight_layout=True))

        # Get the canvas to take up the majority of the screen most of the time
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        figure = canvas.figure
        top_ax = figure.add_subplot(2, 1, 1)
        bottom_ax = figure.add_subplot(2, 1, 2, sharex=top_ax)

        top_ax.set_ylabel(r'$\eta$ (deg)')
        bottom_ax.set_ylabel(r'$\eta$ (deg)')
        bottom_ax.set_xlabel(r'2$\theta$ (deg)')
        top_ax.label_outer()

        top_ax.set_title('Binned')
        bottom_ax.set_title('Simulated')

        axes = [top_ax, bottom_ax]

        axes_images = []
        for i, ax in enumerate(axes):
            axes_images.append(
                ax.imshow(
                    self.get_scaled_image_data(i),
                    extent=self.extent,  # type: ignore[arg-type]
                    cmap=self.cmap,
                    norm=self.norm,
                )
            )

        for ax in axes:
            ax.relim()
            ax.autoscale_view()
            ax.axis('auto')

        figure.tight_layout()
        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)

        # Center the toolbar
        self.ui.canvas_layout.setAlignment(self.toolbar, Qt.AlignmentFlag.AlignCenter)

        self.figure = figure
        self.axes = axes
        self.axes_images = axes_images
        self.canvas = canvas

        self.draw_later()

    def set_cmap(self, cmap: str | mpl.colors.Colormap) -> None:
        self.cmap = cmap
        for im in self.axes_images:
            im.set_cmap(cmap)

        self.draw_later()

    def set_norm(self, norm: mpl.colors.Normalize | None) -> None:
        self.norm = norm
        for im in self.axes_images:
            im.set_norm(norm)

        self.draw_later()

    def set_scaling(self, transform: Callable[[np.ndarray], np.ndarray]) -> None:
        self.transform = transform
        for i, im in enumerate(self.axes_images):
            im.set_data(self.get_scaled_image_data(i))

        self.draw_later()

    @property
    def data(self) -> np.ndarray:
        # Just stack together the top and bottom arrays.
        # This is necessary for things like B&C editor
        return np.stack([self.get_data(i) for i in range(2)])

    @property
    def scaled_image_data(self) -> np.ndarray:
        return self.transform(self.data)

    def set_data(self, pv_bin: np.ndarray, pv_sim: np.ndarray | None) -> None:
        if pv_sim is None:
            pv_sim = np.zeros_like(pv_bin)

        self.pv_bin = pv_bin
        self.pv_sim = pv_sim
        self.on_data_modified()

    def on_data_modified(self) -> None:
        for i, ax_im in enumerate(self.axes_images):
            ax_im.set_data(self.get_scaled_image_data(i))
            ax_im.set_extent(self.extent)  # type: ignore[arg-type]

        self.color_map_editor.data = unmasked(self.data)

        self.draw_later()

    def get_data(self, i: int) -> np.ndarray:
        return self.pv_bin if i == 0 else self.pv_sim

    def get_scaled_image_data(self, i: int) -> np.ndarray:
        return self.transform(self.get_data(i))

    def show(self) -> None:
        self.ui.show()

    def draw_later(self) -> None:
        self.figure.canvas.draw_idle()


def unmasked(
    array: np.ndarray | np.ma.MaskedArray,
    fill_value: float = np.nan,
) -> np.ndarray:
    if isinstance(array, np.ma.MaskedArray):
        return array.filled(fill_value)

    return array
