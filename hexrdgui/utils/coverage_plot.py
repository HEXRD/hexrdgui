"""Coverage plot dialog for viewing detector coverage in polar mode."""

import numpy as np
from PySide6.QtWidgets import QDialog, QVBoxLayout
from PySide6.QtCore import Qt

from matplotlib.backends.backend_qtagg import FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import AutoLocator, AutoMinorLocator

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.calibration.polar_plot import polar_viewer

# Font size increases matching image_canvas.py
FONTSIZE_LABEL_INCREASE = 4
FONTSIZE_TICKS_INCREASE = 4

def calculate_coverage_data(polar_view, nan_mask):
    """Calculate coverage data from polar view.

    this portion calculates the total solid angle that
    is captured as the % of maximum possible i.e. hemisphere

    Args:
        polar_view: PolarView instance
        nan_mask: Boolean mask indicating NaN/masked pixels
    """
    instr = polar_view.instr
    sa_total = 0.0

    for k, v in instr.detectors.items():
        sa_total += v.pixel_solid_angles.sum()

    frac_sa = sa_total/2/np.pi
    msg = fr"total covered solid angle out of 2$\pi$ is {frac_sa*100:.1f}%"

    tth = np.degrees(polar_view.angular_grid[1][0,:])
    azimuthal_frac = 100*np.nansum(~nan_mask, axis=0)/nan_mask.shape[0]

    return (tth, azimuthal_frac), msg

class CoveragePlotDialog(QDialog):
    """Dialog displaying live-updating coverage plot for polar view."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Coverage")
        # self.resize(800, 600)

        # Create matplotlib figure and canvas
        self.figure = Figure(figsize=(12, 4))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)

        # Initialize plot with empty data (black line matching azimuthal average)
        self.line, = self.ax.plot([], [], '-k', linewidth=2.5)

        # Setup axis styling to match polar view azimuthal average
        self._setup_axis_style()

        # Setup layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        # Adjust subplot parameters to prevent label clipping
        self.figure.tight_layout()

        # Connect to HexrdConfig signals for live updates
        HexrdConfig().rerender_needed.connect(self.update_plot)
        HexrdConfig().instrument_config_loaded.connect(self.update_plot)
        HexrdConfig().detector_transforms_modified.connect(self.on_detector_transforms_modified)

        # Track parent UI for menu action access
        self._parent_ui = parent

    def _setup_axis_style(self):
        """Setup axis styling to match polar view azimuthal average plot."""
        # Get font sizes from HexrdConfig (matching image_canvas.py)
        base_font_size = HexrdConfig().font_size
        label_fontsize = base_font_size + FONTSIZE_LABEL_INCREASE
        ticks_fontsize = base_font_size + FONTSIZE_TICKS_INCREASE

        # Set labels with serif font
        self.ax.set_xlabel(r'2$\theta$ [deg]', fontsize=label_fontsize, family='serif')
        self.ax.set_ylabel(r'% azimuthal coverage', fontsize=label_fontsize, family='serif')

        # Setup major and minor tick locators
        self.ax.yaxis.set_major_locator(AutoLocator())
        self.ax.yaxis.set_minor_locator(AutoMinorLocator())
        self.ax.xaxis.set_major_locator(AutoLocator())
        self.ax.xaxis.set_minor_locator(AutoMinorLocator())

        # Configure tick parameters (matching image_canvas.py)
        major_tick_kwargs = {
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
        default_grid_kwargs = {
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

    def on_detector_transforms_modified(self, detectors):
        """Called when detector transforms (translation/tilt) are modified."""
        self.update_plot()

    def update_plot(self):
        """Update the plot with current coverage data."""
        # Only update if dialog is visible
        if not self.isVisible():
            return

        # Get fresh polar viewer instance (reflects current config)
        polar_viewer = self._get_polar_viewer()
        if polar_viewer is None:
            return

        # Get the warped image and compute nan mask
        if polar_viewer.raw_img is None:
            return

        # Use the mask from the masked array
        nan_mask = polar_viewer.raw_img.mask

        # Calculate coverage data
        (x_data, y_data), msg = calculate_coverage_data(polar_viewer, nan_mask)
        y_mean = np.nanmean(y_data) * np.ones_like(x_data)

        msg2 = fr"Average azimuthal coverage in 2$\theta$ FOV = {np.nanmean(y_data):0.1f}%"

        # Clear and redraw with proper styling
        self.ax.clear()
        self._setup_axis_style()

        # Plot data with black line matching azimuthal average
        self.line, = self.ax.plot(x_data, y_data, '-k', linewidth=2.5)

        # Plot average coverage over angular field of view
        self.line, = self.ax.plot(x_data, y_mean, '--k', linewidth=2.5)

        # Add centered text annotation with smaller font
        base_font_size = HexrdConfig().font_size
        text_fontsize = base_font_size + 2  # Slightly smaller than labels
        self.ax.text(0.5, 0.95, msg, transform=self.ax.transAxes,
                    fontsize=text_fontsize, color='red',
                    ha='center', va='top', family='serif')
        self.ax.text(0.5, 0.85, msg2, transform=self.ax.transAxes,
                    fontsize=text_fontsize, color='red',
                    ha='center', va='top', family='serif')

        # Apply tight layout to prevent label clipping
        self.figure.tight_layout()

        # Redraw canvas (non-blocking)
        self.canvas.draw_idle()

    def _get_polar_viewer(self):
        """Get the current polar viewer instance.

        Creates a fresh InstrumentViewer to reflect current configuration.
        """
        try:
            instrument_viewer = polar_viewer()
            if hasattr(instrument_viewer, 'pv'):
                return instrument_viewer.pv
        except Exception:
            pass
        return None

    def show(self):
        """Show the dialog and update plot."""
        super().show()
        self.update_plot()

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Uncheck the menu action when dialog is closed
        if self._parent_ui and hasattr(self._parent_ui, 'action_view_coverage'):
            self._parent_ui.action_view_coverage.setChecked(False)

        # Disconnect signals to prevent memory leaks
        # Use try-except to handle cases where signals are already disconnected
        try:
            HexrdConfig().rerender_needed.disconnect(self.update_plot)
        except (RuntimeError, TypeError):
            pass

        try:
            HexrdConfig().instrument_config_loaded.disconnect(self.update_plot)
        except (RuntimeError, TypeError):
            pass

        try:
            HexrdConfig().detector_transforms_modified.disconnect(self.on_detector_transforms_modified)
        except (RuntimeError, TypeError):
            pass

        super().closeEvent(event)
