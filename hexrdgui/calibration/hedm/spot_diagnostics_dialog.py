from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader


# Quantity definitions: key -> (label, combo_label, units, default_bounds)
# combo_label uses Unicode for Qt widgets; label uses LaTeX for matplotlib
QUANTITY_CONFIG = {
    'tth': {
        'label': r'$2\theta$',
        'combo_label': '2θ',
        'units': 'degrees',
        'default_bounds': 0.01,
    },
    'eta': {
        'label': r'$\eta$',
        'combo_label': 'η',
        'units': 'degrees',
        'default_bounds': 0.05,
    },
    'ome': {
        'label': r'$\omega$',
        'combo_label': 'ω',
        'units': 'degrees',
        'default_bounds': 0.4,
    },
    'x': {
        'label': 'X',
        'combo_label': 'X',
        'units': 'mm',
        'default_bounds': 0.2,
    },
    'y': {
        'label': 'Y',
        'combo_label': 'Y',
        'units': 'mm',
        'default_bounds': 0.2,
    },
}


def extract_spot_angles(
    spots_data: Any,
    instr: Any,
    grain_ids: np.ndarray,
) -> tuple[dict[str, list[np.ndarray]], dict[str, list[np.ndarray]]]:
    """Extract predicted and measured angles from raw spots data.

    Returns:
        pred_angs: {det_key: [Nx3 array per grain]} predicted [tth, eta, ome]
        meas_angs: {det_key: [Nx3 array per grain]} measured [tth, eta, ome]

    Uses the same filtering as parse_spots_data (valid reflections,
    not saturated).
    """
    pred_angs: dict[str, list[np.ndarray]] = {}
    meas_angs: dict[str, list[np.ndarray]] = {}

    for det_key, panel in instr.detectors.items():
        pred_angs[det_key] = []
        meas_angs[det_key] = []

        for grain_id in grain_ids:
            data = spots_data[grain_id][1][det_key]
            data = np.array(data, dtype=object)

            if data.size == 0:
                pred_angs[det_key].append(np.empty((0, 3)))
                meas_angs[det_key].append(np.empty((0, 3)))
                continue

            valid_reflections = data[:, 0] >= 0
            not_saturated = data[:, 4] < panel.saturation_level
            idx = np.logical_and(valid_reflections, not_saturated)

            if not np.any(idx):
                pred_angs[det_key].append(np.empty((0, 3)))
                meas_angs[det_key].append(np.empty((0, 3)))
                continue

            pred_angs[det_key].append(np.vstack(data[idx, 5]))
            meas_angs[det_key].append(np.vstack(data[idx, 6]))

    return pred_angs, meas_angs


class SpotDiagnosticsDialog:
    def __init__(
        self,
        pred_angs: dict[str, list[np.ndarray]],
        meas_angs: dict[str, list[np.ndarray]],
        xyo_pred: dict[str, list[np.ndarray]],
        xyo_det: dict[str, list[np.ndarray]],
        grain_ids: list[int] | np.ndarray,
        det_keys: list[str],
        parent: QWidget | None = None,
    ) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('spot_diagnostics_dialog.ui', parent)

        if isinstance(grain_ids, np.ndarray):
            grain_ids = grain_ids.tolist()

        self.pred_angs = pred_angs
        self.meas_angs = meas_angs
        self.xyo_pred = xyo_pred
        self.xyo_det = xyo_det
        self.grain_ids = grain_ids
        self.det_keys = det_keys

        self.setup_combo_boxes()
        self.setup_canvas()
        self.setup_connections()
        self.update_canvas()

    def setup_connections(self) -> None:
        self.ui.quantity.currentIndexChanged.connect(
            self.on_quantity_changed,
        )
        self.ui.bounds.valueChanged.connect(self.update_canvas)
        self.ui.histogram_bins.valueChanged.connect(self.update_canvas)
        self.ui.detector.currentIndexChanged.connect(self.update_canvas)
        self.ui.show_all_grains.toggled.connect(self.show_all_grains_toggled)
        self.ui.grain_id.currentIndexChanged.connect(self.update_canvas)

    def setup_combo_boxes(self) -> None:
        self.ui.quantity.clear()
        for key, config in QUANTITY_CONFIG.items():
            combo_label = f"{config['combo_label']} ({config['units']})"
            self.ui.quantity.addItem(combo_label, key)

        self.ui.detector.clear()
        for det_key in self.det_keys:
            self.ui.detector.addItem(det_key)

        self.ui.grain_id.clear()
        for grain_id in sorted(self.grain_ids):
            self.ui.grain_id.addItem(str(grain_id), grain_id)

        self.update_enable_states()

    def update_enable_states(self) -> None:
        enable_grain_id = (
            not self.show_all_grains and self.ui.grain_id.count() > 1
        )
        self.ui.grain_id.setEnabled(enable_grain_id)
        self.ui.grain_id_label.setEnabled(enable_grain_id)

        enable_detector = self.ui.detector.count() > 1
        self.ui.detector.setEnabled(enable_detector)
        self.ui.detector_label.setEnabled(enable_detector)

        show_all_grains_visible = self.ui.grain_id.count() > 1
        self.ui.show_all_grains.setVisible(show_all_grains_visible)

    def setup_canvas(self) -> None:
        canvas = FigureCanvas(Figure(constrained_layout=True))
        canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.ui.canvas_layout.addWidget(canvas)

        self.toolbar = NavigationToolbar(canvas, self.ui, coordinates=True)
        self.ui.canvas_layout.addWidget(self.toolbar)
        self.ui.canvas_layout.setAlignment(
            self.toolbar, Qt.AlignmentFlag.AlignCenter,
        )

        self.fig = canvas.figure
        self.canvas = canvas

    def update_data(
        self,
        xyo_pred: dict[str, list[np.ndarray]],
    ) -> None:
        """Update predicted positions and refresh plots.

        Called after calibration to reflect updated model predictions.
        """
        self.xyo_pred = xyo_pred
        self.update_canvas()

    @property
    def is_visible(self) -> bool:
        return self.ui.isVisible()

    def show(self) -> None:
        self.ui.show()

    def exec(self) -> int:
        return self.ui.exec()

    @property
    def selected_quantity(self) -> str:
        return self.ui.quantity.currentData()

    @property
    def selected_detector_key(self) -> str:
        return self.ui.detector.currentText()

    @property
    def selected_grain_id(self) -> int:
        return self.ui.grain_id.currentData()

    @property
    def show_all_grains(self) -> bool:
        return self.ui.show_all_grains.isChecked()

    @property
    def bounds_value(self) -> float:
        return self.ui.bounds.value()

    @property
    def num_bins(self) -> int:
        return self.ui.histogram_bins.value()

    @property
    def grain_indices_to_plot(self) -> list[int]:
        if self.show_all_grains:
            return list(range(len(self.grain_ids)))
        return [self.grain_ids.index(self.selected_grain_id)]

    def on_quantity_changed(self) -> None:
        key = self.selected_quantity
        if key is not None:
            config = QUANTITY_CONFIG[key]
            self.ui.bounds.setValue(config['default_bounds'])
        self.update_canvas()

    def show_all_grains_toggled(self) -> None:
        self.update_enable_states()
        self.update_canvas()

    def _get_data_for_quantity(
        self,
        det_key: str,
        grain_idx: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get predicted, measured, and scatter positions for a quantity.

        Returns:
            exp_val: predicted values (degrees or mm)
            sim_val: measured values (degrees or mm)
            scatter_x: X positions for spatial scatter
            scatter_y: Y positions for spatial scatter
        """
        key = self.selected_quantity

        pred_a = self.pred_angs[det_key][grain_idx]
        meas_a = self.meas_angs[det_key][grain_idx]
        xyo_p = self.xyo_pred[det_key][grain_idx]
        xyo_m = self.xyo_det[det_key][grain_idx]

        # Use predicted detector XY for scatter positions
        scatter_x = xyo_p[:, 0]
        scatter_y = xyo_p[:, 1]

        if key == 'tth':
            exp_val = np.degrees(pred_a[:, 0])
            sim_val = np.degrees(meas_a[:, 0])
        elif key == 'eta':
            exp_val = np.degrees(pred_a[:, 1])
            sim_val = np.degrees(meas_a[:, 1])
        elif key == 'ome':
            exp_val = np.degrees(pred_a[:, 2])
            sim_val = np.degrees(meas_a[:, 2])
        elif key == 'x':
            exp_val = xyo_p[:, 0]
            sim_val = xyo_m[:, 0]
        elif key == 'y':
            exp_val = xyo_p[:, 1]
            sim_val = xyo_m[:, 1]
        else:
            raise ValueError(f'Unknown quantity: {key}')

        return exp_val, sim_val, scatter_x, scatter_y

    def update_canvas(self) -> None:
        # Clear the entire figure (removes all axes including colorbars)
        self.fig.clear()

        key = self.selected_quantity
        det_key = self.selected_detector_key
        if key is None or not det_key:
            self.canvas.draw()
            return

        config = QUANTITY_CONFIG[key]
        bounds = self.bounds_value
        nbins = self.num_bins
        label = config['label']
        units = config['units']

        grain_indices = self.grain_indices_to_plot

        # Collect all data across selected grains
        all_diff = []
        all_exp = []
        all_scatter_x = []
        all_scatter_y = []

        for grain_idx in grain_indices:
            exp_val, sim_val, sx, sy = self._get_data_for_quantity(
                det_key, grain_idx,
            )
            if exp_val.size == 0:
                continue

            diff = sim_val - exp_val
            all_diff.append(diff)
            all_exp.append(exp_val)
            all_scatter_x.append(sx)
            all_scatter_y.append(sy)

        if not all_diff:
            self.fig.text(
                0.5, 0.5, 'No spot data',
                ha='center', va='center', fontsize=16, color='gray',
            )
            self.canvas.draw()
            return

        all_diff = np.concatenate(all_diff)
        all_exp = np.concatenate(all_exp)
        all_scatter_x = np.concatenate(all_scatter_x)
        all_scatter_y = np.concatenate(all_scatter_y)

        # Recreate subplots fresh each time (avoids colorbar accumulation)
        ax_hist, ax_scatter, ax_line = self.fig.subplots(1, 3)

        diff_label = f'{label}' + r'$_{Meas}$' + f' - {label}' + r'$_{Pred}$'
        diff_with_units = f'{diff_label} ({units})'

        # 1. Histogram
        bins = np.linspace(-bounds, bounds, nbins)
        ax_hist.hist(all_diff, bins, edgecolor='black', linewidth=0.5)
        ax_hist.set_xlabel(diff_with_units)
        ax_hist.set_ylabel('Number of Spots')
        ax_hist.set_xlim(-bounds, bounds)
        ax_hist.set_title('Residual Histogram')

        # 2. Spatial scatter plot
        sc = ax_scatter.scatter(
            all_scatter_x,
            all_scatter_y,
            c=all_diff,
            cmap='turbo',
            vmin=-bounds,
            vmax=bounds,
            s=10,
        )
        self.fig.colorbar(sc, ax=ax_scatter, label=diff_with_units)
        ax_scatter.set_xlabel(r'$X^{D}$ (mm)')
        ax_scatter.set_ylabel(r'$Y^{D}$ (mm)')
        ax_scatter.set_title('Spatial Distribution')

        # 3. Line/scatter plot vs quantity
        # (y-axis label omitted — the adjacent colorbar already shows it)
        ax_line.scatter(all_exp, all_diff, s=5, alpha=0.5)
        ax_line.set_ylim(-bounds, bounds)
        ax_line.set_xlabel(f'{label}' + r'$_{Pred}$' + f' ({units})')
        ax_line.set_title(f'Residual vs {label}')

        self.canvas.draw()
