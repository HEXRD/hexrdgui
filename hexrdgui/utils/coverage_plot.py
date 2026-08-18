"""Coverage plot dialog for viewing detector coverage in polar mode."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator, AutoMinorLocator
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from hexrdgui.constants import ViewType
from hexrdgui.hexrd_config import HexrdConfig

if TYPE_CHECKING:
    from hexrdgui.calibration.polar_plot import InstrumentViewer

# Font size increases matching image_canvas.py
FONTSIZE_LABEL_INCREASE = 4
FONTSIZE_TICKS_INCREASE = 4


def calculate_coverage_data(
    polar_view: 'InstrumentViewer',
) -> tuple[tuple[np.ndarray, np.ndarray], str]:
    """Calculate coverage data from the polar view.

    Returns the azimuthal coverage (in %) as a function of two-theta,
    along with a message describing the total solid angle captured as a
    % of the maximum possible (i.e. hemisphere).
    """
    instr = polar_view.instr

    # Calculate total solid angle, excluding panel buffer pixels
    sa_total = 0.0
    for panel in instr.detectors.values():
        pixel_sa = panel.pixel_solid_angles

        # Check if panel has a buffer set
        if panel.panel_buffer is not None and np.any(panel.panel_buffer):
            # panel_buffer is True for masked/buffered pixels, False for valid pixels
            # So we want to sum solid angles where panel_buffer is False (not buffered)
            panel_buffer = np.asarray(panel.panel_buffer, dtype=bool)
            valid_mask = ~panel_buffer
            sa_total += pixel_sa[valid_mask].sum()
        else:
            # No panel buffer, count all pixels
            sa_total += pixel_sa.sum()

    frac_sa = sa_total / 2 / np.pi
    msg = f'Total covered solid angle out of 2π is {frac_sa * 100:.1f}%'

    raw_img = polar_view.raw_img
    assert raw_img is not None
    nan_mask = np.ma.getmaskarray(raw_img)
    tth = np.degrees(polar_view.angular_grid[1][0, :])
    azimuthal_frac = 100 * (~nan_mask).sum(axis=0) / nan_mask.shape[0]

    return (tth, azimuthal_frac), msg


class CoveragePlotDialog(QDialog):
    """Dialog displaying live-updating coverage plot for polar view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle('Coverage')

        # Create matplotlib figure and canvas
        self.figure = Figure(figsize=(12, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)

        # Coverage curve and its average (black lines matching the
        # azimuthal average plot)
        (self.coverage_line,) = self.ax.plot([], [], '-k', linewidth=2.5)
        (self.mean_line,) = self.ax.plot([], [], '--k', linewidth=2.5)

        # Setup axis styling to match polar view azimuthal average
        self._setup_axis_style()

        # Centered summary labels displayed above the plot, with a font
        # size matching the plot's axis labels
        self.solid_angle_label = QLabel()
        self.average_label = QLabel()
        for label in (self.solid_angle_label, self.average_label):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = label.font()
            font.setPointSize(HexrdConfig().font_size + FONTSIZE_LABEL_INCREASE)
            label.setFont(font)

        # Setup layout
        layout = QVBoxLayout()
        layout.addWidget(self.solid_angle_label)
        layout.addWidget(self.average_label)
        layout.addWidget(self.canvas)

        footer_layout = QHBoxLayout()
        self.coordinates_label = QLabel()
        self.export_button = QPushButton('Export Lineout')
        footer_layout.addWidget(self.coordinates_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.export_button)
        layout.addLayout(footer_layout)
        self.setLayout(layout)

        # Adjust subplot parameters to prevent label clipping
        self.figure.tight_layout()

        self.setup_connections()

    def setup_connections(self) -> None:
        # The image canvas emits this after it finishes regenerating the
        # view, so we can reuse its polar view rather than computing our
        # own. This covers rerenders, config loads, etc.
        HexrdConfig().image_view_loaded.connect(self.update_plot)

        # Interactive detector translation/tilt edits update the canvas's
        # polar view in place without emitting image_view_loaded, so listen
        # for those separately. The image canvas connects to this signal
        # before this dialog is created, so its polar view has already been
        # updated by the time our slot runs.
        HexrdConfig().detector_transforms_modified.connect(self.update_plot)

        self.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.export_button.clicked.connect(self.export_lineout)

    def on_mouse_move(self, event: Any) -> None:
        if event.inaxes is not self.ax:
            self.coordinates_label.clear()
            return

        self.coordinates_label.setText(
            f'tth={event.xdata:.2f},  coverage={event.ydata:.1f}%'
        )

    def export_lineout(self) -> None:
        default_path = Path(HexrdConfig().working_dir) / 'azimuthal_coverage.xy'
        selected_file, _ = QFileDialog.getSaveFileName(
            self,
            'Export Azimuthal Coverage',
            str(default_path),
            'XY files (*.xy)',
        )
        if not selected_file:
            return

        path = Path(selected_file)
        if path.suffix.lower() != '.xy':
            path = Path(f'{path}.xy')

        HexrdConfig().working_dir = str(path.parent)
        x_data, y_data = self.coverage_line.get_data()
        np.savetxt(path, np.column_stack((x_data, y_data)))

    @property
    def polar_view(self) -> 'InstrumentViewer | None':
        """The active canvas's polar view, or None if not in polar mode."""
        canvas = HexrdConfig().active_canvas
        if canvas is None or canvas.mode != ViewType.polar:
            return None
        return cast('InstrumentViewer', canvas.iviewer)

    def _setup_axis_style(self) -> None:
        """Setup axis styling to match polar view azimuthal average plot."""
        # Get font sizes from HexrdConfig (matching image_canvas.py)
        base_font_size = HexrdConfig().font_size
        label_fontsize = base_font_size + FONTSIZE_LABEL_INCREASE
        ticks_fontsize = base_font_size + FONTSIZE_TICKS_INCREASE

        # Set labels with serif font
        self.ax.set_xlabel(r'2$\theta$ [deg]', fontsize=label_fontsize, family='serif')
        self.ax.set_ylabel(
            r'% azimuthal coverage', fontsize=label_fontsize, family='serif'
        )

        # Setup major and minor tick locators
        self.ax.yaxis.set_major_locator(AutoLocator())
        self.ax.yaxis.set_minor_locator(AutoMinorLocator())
        self.ax.xaxis.set_major_locator(AutoLocator())
        self.ax.xaxis.set_minor_locator(AutoMinorLocator())

        # Configure tick parameters (matching image_canvas.py)
        major_tick_kwargs: dict[str, Any] = {
            'left': True,
            'right': True,
            'bottom': True,
            'top': True,
            'which': 'major',
            'length': 10,
            'labelfontfamily': 'serif',
            'labelsize': ticks_fontsize,
        }

        minor_tick_kwargs = {
            **major_tick_kwargs,
            'which': 'minor',
            'length': 2,
        }

        self.ax.tick_params(**major_tick_kwargs)
        self.ax.tick_params(**minor_tick_kwargs)

        # Setup grid (matching polar axis style)
        default_grid_kwargs: dict[str, Any] = {
            'visible': True,
            'linewidth': 0.075,
            'linestyle': '--',
            'color': 'k',
            'alpha': 0.9,
        }

        # Grid for minor y ticks
        self.ax.grid(
            **{
                **default_grid_kwargs,
                'which': 'minor',
                'axis': 'y',
                'linewidth': 0.25,
                'linestyle': '-',
                'alpha': 0.75,
            }
        )

        # Grid for major ticks
        self.ax.grid(**{**default_grid_kwargs, 'which': 'major'})

    def update_plot(self, *args: Any) -> None:
        """Update the plot with current coverage data."""
        # Only update if dialog is visible
        if not self.isVisible():
            return

        if HexrdConfig().loading_state:
            # A rerender will occur when state loading finishes
            return

        polar_view = self.polar_view
        if polar_view is None or polar_view.raw_img is None:
            return

        (x_data, y_data), solid_angle_msg = calculate_coverage_data(polar_view)
        mean = np.nanmean(y_data)

        self.coverage_line.set_data(x_data, y_data)
        self.mean_line.set_data(x_data, np.full_like(x_data, mean))
        self.solid_angle_label.setText(solid_angle_msg)
        self.average_label.setText(
            f'Average azimuthal coverage in 2θ FOV = {mean:0.1f}%'
        )

        self.ax.relim()
        self.ax.autoscale_view()

        # Redraw canvas (non-blocking)
        self.canvas.draw_idle()

    def show(self) -> None:
        """Show the dialog and update plot."""
        super().show()
        self.update_plot()
