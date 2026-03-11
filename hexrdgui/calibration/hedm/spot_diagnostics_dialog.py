from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils.dialog import add_help_url
from hexrdgui.utils.spots import extract_spot_angles, extract_spot_xyo

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.collections import PathCollection
    from numpy.typing import NDArray

    from hexrd.core.instrument import HEDMInstrument

    from hexrdgui.utils.spots import DetGrainArrays, SpotsData


# Quantity definitions: key -> (label, combo_label, units, default_bounds)
# combo_label uses Unicode for Qt widgets; label uses LaTeX for matplotlib
QUANTITY_CONFIG: dict[str, dict[str, str | float]] = {
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


def _extract_detector_info(
    instr: HEDMInstrument,
) -> tuple[list[str], dict[str, tuple[float, float]], dict[str, NDArray[np.floating]]]:
    """Extract det_keys, det_dims, and det_tvecs from an instrument."""
    det_keys = list(instr.detectors)
    det_dims = {
        k: (panel.col_dim, panel.row_dim) for k, panel in instr.detectors.items()
    }
    det_tvecs = {k: panel.tvec.copy() for k, panel in instr.detectors.items()}
    return det_keys, det_dims, det_tvecs


class SpotDiagnosticsDialog:
    """Dialog for visualizing spot residuals (pred vs meas).

    There are two ways to construct this dialog:

    1. **From raw spots data** (fit-grains path): pass ``instr``,
       ``spots_data``, and ``grain_ids``.  The dialog will compute
       ``pred_angs``, ``meas_angs``, ``xyo_pred``, and ``xyo_det``
       internally.

    2. **With pre-computed arrays** (HEDM calibration path): also pass
       ``pred_angs``, ``meas_angs``, ``xyo_pred``, and/or ``xyo_det``
       to override the values derived from ``spots_data``.
    """

    def __init__(
        self,
        instr: HEDMInstrument,
        spots_data: SpotsData,
        grain_ids: list[int] | NDArray[np.integer],
        *,
        pred_angs: DetGrainArrays | None = None,
        meas_angs: DetGrainArrays | None = None,
        xyo_pred: DetGrainArrays | None = None,
        xyo_det: DetGrainArrays | None = None,
        parent: QWidget | None = None,
    ) -> None:
        loader = UiLoader()
        self.ui = loader.load_file('spot_diagnostics_dialog.ui', parent)

        self.grain_ids: list[int] = (
            grain_ids.tolist() if isinstance(grain_ids, np.ndarray) else grain_ids
        )

        # Derive detector info from instrument
        det_keys, det_dims, det_tvecs = _extract_detector_info(instr)
        self.det_keys: list[str] = det_keys
        self.det_dims: dict[str, tuple[float, float]] = det_dims
        self.det_tvecs: dict[str, NDArray[np.floating]] = det_tvecs

        # Compute from spots_data, then allow overrides
        default_pred_angs, default_meas_angs = extract_spot_angles(
            spots_data,
            instr,
            self.grain_ids,
        )
        default_xyo_pred, default_xyo_det = extract_spot_xyo(
            spots_data,
            instr,
            self.grain_ids,
        )

        self.pred_angs: DetGrainArrays = (
            pred_angs if pred_angs is not None else default_pred_angs
        )
        self.meas_angs: DetGrainArrays = (
            meas_angs if meas_angs is not None else default_meas_angs
        )
        self.xyo_pred: DetGrainArrays = (
            xyo_pred if xyo_pred is not None else default_xyo_pred
        )
        self.xyo_det: DetGrainArrays = (
            xyo_det if xyo_det is not None else default_xyo_det
        )

        self.fig: Figure | None = None
        self.canvas: FigureCanvas | None = None
        self.toolbar: NavigationToolbar | None = None

        self.setup_combo_boxes()
        self.setup_canvas()
        self.setup_connections()
        add_help_url(
            self.ui.button_box,
            'calibration/rotation_series/#spot-diagnostics',
        )
        self.update_canvas()

    def setup_connections(self) -> None:
        self.ui.quantity.currentIndexChanged.connect(
            self.on_quantity_changed,
        )
        self.ui.bounds.valueChanged.connect(self.update_canvas)
        self.ui.histogram_bins.valueChanged.connect(self.update_canvas)
        self.ui.show_all_detectors.toggled.connect(
            self.show_all_detectors_toggled,
        )
        self.ui.detector.currentIndexChanged.connect(self.update_canvas)
        self.ui.show_all_grains.toggled.connect(self.show_all_grains_toggled)
        self.ui.grain_id.currentIndexChanged.connect(self.update_canvas)
        self.ui.match_detector_shape.toggled.connect(self.update_canvas)

    def setup_combo_boxes(self) -> None:
        self.ui.quantity.clear()
        for key, config in QUANTITY_CONFIG.items():
            combo_label = f'{config["combo_label"]} ({config["units"]})'
            self.ui.quantity.addItem(combo_label, key)

        self.ui.detector.clear()
        for det_key in self.det_keys:
            self.ui.detector.addItem(det_key)

        self.ui.grain_id.clear()
        for grain_id in sorted(self.grain_ids):
            self.ui.grain_id.addItem(str(grain_id), grain_id)

        self.update_enable_states()

    def update_enable_states(self) -> None:
        enable_grain_id = not self.show_all_grains and self.ui.grain_id.count() > 1
        self.ui.grain_id.setEnabled(enable_grain_id)
        self.ui.grain_id_label.setEnabled(enable_grain_id)

        show_all_grains_visible: bool = self.ui.grain_id.count() > 1
        self.ui.show_all_grains.setVisible(show_all_grains_visible)

        enable_detector = not self.show_all_detectors and self.ui.detector.count() > 1
        self.ui.detector.setEnabled(enable_detector)
        self.ui.detector_label.setEnabled(enable_detector)

        show_all_detectors_visible: bool = self.ui.detector.count() > 1
        self.ui.show_all_detectors.setVisible(show_all_detectors_visible)

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
            self.toolbar,
            Qt.AlignmentFlag.AlignCenter,
        )

        self.fig = canvas.figure
        self.canvas = canvas

    def update_data(
        self,
        instr: HEDMInstrument,
        *,
        xyo_pred: DetGrainArrays,
        pred_angs: DetGrainArrays,
        meas_angs: DetGrainArrays,
    ) -> None:
        """Update data after calibration refinement and refresh plots.

        The instrument may have changed (e.g. detector translations),
        so detector info is re-derived.  The caller provides recomputed
        predicted/measured arrays from the calibrator model.
        """
        _, self.det_dims, self.det_tvecs = _extract_detector_info(instr)
        self.xyo_pred = xyo_pred
        self.pred_angs = pred_angs
        self.meas_angs = meas_angs
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
    def show_all_detectors(self) -> bool:
        return self.ui.show_all_detectors.isChecked()

    @property
    def match_detector_shape(self) -> bool:
        return self.ui.match_detector_shape.isChecked()

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

    @property
    def det_keys_to_plot(self) -> list[str]:
        if self.show_all_detectors:
            return self.det_keys
        return [self.selected_detector_key]

    def on_quantity_changed(self) -> None:
        key = self.selected_quantity
        if key is not None:
            config = QUANTITY_CONFIG[key]
            self.ui.bounds.setValue(config['default_bounds'])
        self.update_canvas()

    def show_all_grains_toggled(self) -> None:
        self.update_enable_states()
        self.update_canvas()

    def show_all_detectors_toggled(self) -> None:
        self.update_enable_states()
        self.update_canvas()

    def _get_data_for_quantity(
        self,
        det_key: str,
        grain_idx: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get predicted, measured, and scatter positions for a quantity.

        Returns
        -------
        exp_val
            Predicted values (degrees or mm).
        sim_val
            Measured values (degrees or mm).
        scatter_x
            X positions for spatial scatter.
        scatter_y
            Y positions for spatial scatter.
        """
        key = self.selected_quantity

        pred_a = self.pred_angs[det_key][grain_idx]
        meas_a = self.meas_angs[det_key][grain_idx]
        xyo_p = self.xyo_pred[det_key][grain_idx]
        xyo_m = self.xyo_det[det_key][grain_idx]

        # Offset XY by detector translation to place in instrument frame
        tvec = self.det_tvecs[det_key]
        scatter_x: np.ndarray = xyo_p[:, 0] + tvec[0]
        scatter_y: np.ndarray = xyo_p[:, 1] + tvec[1]

        exp_val: np.ndarray
        sim_val: np.ndarray
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
            exp_val = xyo_p[:, 0] + tvec[0]
            sim_val = xyo_m[:, 0] + tvec[0]
        elif key == 'y':
            exp_val = xyo_p[:, 1] + tvec[1]
            sim_val = xyo_m[:, 1] + tvec[1]
        else:
            raise ValueError(f'Unknown quantity: {key}')

        return exp_val, sim_val, scatter_x, scatter_y

    def update_canvas(self) -> None:
        assert self.fig is not None
        assert self.canvas is not None

        # Clear the entire figure (removes all axes including colorbars)
        self.fig.clear()

        key = self.selected_quantity
        if key is None:
            self.canvas.draw()
            return

        det_keys = self.det_keys_to_plot
        if not det_keys:
            self.canvas.draw()
            return

        config = QUANTITY_CONFIG[key]
        bounds: float = self.bounds_value
        nbins: int = self.num_bins
        label: str = str(config['label'])
        units: str = str(config['units'])

        grain_indices = self.grain_indices_to_plot

        # Collect all data across selected detectors and grains
        all_diff: list[np.ndarray] = []
        all_exp: list[np.ndarray] = []
        all_scatter_x: list[np.ndarray] = []
        all_scatter_y: list[np.ndarray] = []

        for det_key in det_keys:
            for grain_idx in grain_indices:
                exp_val, sim_val, sx, sy = self._get_data_for_quantity(
                    det_key,
                    grain_idx,
                )
                if exp_val.size == 0:
                    continue

                diff: np.ndarray = sim_val - exp_val
                all_diff.append(diff)
                all_exp.append(exp_val)
                all_scatter_x.append(sx)
                all_scatter_y.append(sy)

        if not all_diff:
            self.fig.text(
                0.5,
                0.5,
                'No spot data',
                ha='center',
                va='center',
                fontsize=16,
                color='gray',
            )
            self.canvas.draw()
            return

        cat_diff: np.ndarray = np.concatenate(all_diff)
        cat_exp: np.ndarray = np.concatenate(all_exp)
        cat_scatter_x: np.ndarray = np.concatenate(all_scatter_x)
        cat_scatter_y: np.ndarray = np.concatenate(all_scatter_y)

        # Recreate subplots fresh each time (avoids colorbar accumulation)
        ax_hist: Axes
        ax_scatter: Axes
        ax_line: Axes
        ax_hist, ax_scatter, ax_line = self.fig.subplots(1, 3)

        diff_label = f'{label}' + r'$_{Meas}$' + f' - {label}' + r'$_{Pred}$'
        diff_with_units = f'{diff_label} ({units})'

        # 1. Histogram
        hist_bins: list[float] = np.linspace(-bounds, bounds, nbins).tolist()
        ax_hist.hist(cat_diff, hist_bins, edgecolor='black', linewidth=0.5)
        ax_hist.set_xlabel(diff_with_units)
        ax_hist.set_ylabel('Number of Spots')
        ax_hist.set_xlim(-bounds, bounds)
        ax_hist.set_title('Residual Histogram')

        # 2. Spatial scatter plot
        sc: PathCollection = ax_scatter.scatter(
            cat_scatter_x,
            cat_scatter_y,
            c=cat_diff,
            cmap='RdBu_r',
            vmin=-bounds,
            vmax=bounds,
            s=10,
        )
        self.fig.colorbar(sc, ax=ax_scatter, label=diff_with_units)
        ax_scatter.set_xlabel(r'$X^{D}$ (mm)')
        ax_scatter.set_ylabel(r'$Y^{D}$ (mm)')
        ax_scatter.set_title('Spatial Distribution')

        if self.match_detector_shape:
            # Compute bounding box of selected detectors in instrument frame
            x_min: float = min(
                self.det_tvecs[k][0] - self.det_dims[k][0] / 2 for k in det_keys
            )
            x_max: float = max(
                self.det_tvecs[k][0] + self.det_dims[k][0] / 2 for k in det_keys
            )
            y_min: float = min(
                self.det_tvecs[k][1] - self.det_dims[k][1] / 2 for k in det_keys
            )
            y_max: float = max(
                self.det_tvecs[k][1] + self.det_dims[k][1] / 2 for k in det_keys
            )
            ax_scatter.set_xlim(x_min, x_max)
            ax_scatter.set_ylim(y_min, y_max)
            ax_scatter.set_aspect('equal')

        # 3. Line/scatter plot vs quantity
        # (y-axis label omitted -- the adjacent colorbar already shows it)
        ax_line.scatter(cat_exp, cat_diff, s=5, alpha=0.5)
        ax_line.set_ylim(-bounds, bounds)
        ax_line.set_xlabel(f'{label}' + r'$_{Pred}$' + f' ({units})')
        ax_line.set_title(f'Residual vs {label}')

        self.canvas.draw()
