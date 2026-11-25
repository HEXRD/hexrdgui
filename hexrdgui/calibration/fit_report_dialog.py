from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QTableWidgetItem, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.navigation_toolbar import NavigationToolbar
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import block_signals

if TYPE_CHECKING:
    from hexrd.core.fitting.calibration import (
        InstrumentCalibrator,
        StructurelessCalibrator,
    )
    from hexrd.core.fitting.calibration.fit_report import RingReport
    from hexrd.core.material import Material


FIT_REFERENCE_LABEL = 'Fitted ring means'

TABLE_COLUMNS = [
    'Overlay',
    'Ring',
    'Points',
    'Detectors',
    'hkl',
    'Fit 2θ (°)',
    'hkl 2θ (°)',
    'Mean 2θ (°)',
    'Offset (°)',
    'σ (°)',
    'σ / 2θ',
]


class RingRow(NamedTuple):
    """The points of one ring on the selected detectors"""

    # The name of the calibrator the ring came from (composite only)
    group: str | None
    label: str
    color: str
    ring: RingReport
    tth: np.ndarray
    eta: np.ndarray
    detectors: np.ndarray
    # The 2θ that residuals are measured from. This is None if a material
    # is the reference, but none of its hkls can diffract.
    reference: float | None


class FitReportDialog:
    """Diagnostic plots of the ring residuals from a calibration

    For each Debye-Scherrer ring, this shows the spread of the measured 2θ
    relative to the ring's 2θ, a histogram of the residuals, and the
    residuals as a function of η (which can reveal geometry errors, such
    as a beam center that is off).

    For structureless calibration, residuals are measured from either the
    fitted ring means or the nearest hkls of a chosen material. For
    composite (and fast powder) calibration, they are measured from the
    hkls of each powder calibrator's material, just as in the calibration.
    Laue picks are spots rather than rings, so they are not included.
    """

    def __init__(
        self,
        calibrator: StructurelessCalibrator | InstrumentCalibrator,
        parent: QWidget | None = None,
        calibrator_names: list[str] | None = None,
    ) -> None:
        """`calibrator_names` names each calibrator of an instrument
        calibrator (such as by its overlay). They default to the materials.
        """
        loader = UiLoader()
        self.ui = loader.load_file('fit_report_dialog.ui', parent)

        self.calibrator = calibrator
        self.calibrator_names = calibrator_names
        self.rings: list[tuple[str | None, RingReport]] = []

        self.setup_combo_boxes()
        self.setup_note()
        self.setup_table()
        self.setup_canvas()
        self.setup_connections()
        self.update_data()

    def setup_connections(self) -> None:
        self.ui.material.currentIndexChanged.connect(self.update_data)
        self.ui.bounds.valueChanged.connect(self.update_canvas)
        self.ui.histogram_bins.valueChanged.connect(self.update_canvas)
        self.ui.show_all_detectors.toggled.connect(self.show_all_detectors_toggled)
        self.ui.detector.currentIndexChanged.connect(self.update_canvas)

    def setup_combo_boxes(self) -> None:
        # Only structureless calibration has a choice of reference
        self.ui.material.setVisible(self.is_structureless)
        self.ui.material_label.setVisible(self.is_structureless)
        self.update_materials()

        self.ui.detector.clear()
        for det_key in self.calibrator.instr.detectors:
            self.ui.detector.addItem(det_key)

        self.update_enable_states()

    def setup_note(self) -> None:
        laue_names = [
            name
            for name, calibrator in self.named_calibrators
            if calibrator.type != 'powder'
        ]
        if laue_names:
            self.ui.note.setText(
                'Laue picks are spots rather than rings, so they are not '
                f'included: {", ".join(laue_names)}'
            )
        self.ui.note.setVisible(bool(laue_names))

    def setup_table(self) -> None:
        table = self.ui.table
        table.setColumnCount(len(TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(TABLE_COLUMNS)

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

    def update_materials(self) -> None:
        if not self.is_structureless:
            return

        # Repopulate the materials, in case they were modified, and keep
        # the current selection if it still exists.
        w = self.ui.material
        current = w.currentData()
        with block_signals(w):
            w.clear()
            w.addItem(FIT_REFERENCE_LABEL, None)
            for name in HexrdConfig().materials:
                w.addItem(name, name)

            idx = w.findData(current) if current is not None else 0
            w.setCurrentIndex(max(idx, 0))

    def update_enable_states(self) -> None:
        enable_detector = not self.show_all_detectors and self.ui.detector.count() > 1
        self.ui.detector.setEnabled(enable_detector)
        self.ui.detector_label.setEnabled(enable_detector)

        show_all_detectors_visible = self.ui.detector.count() > 1
        self.ui.show_all_detectors.setVisible(show_all_detectors_visible)

    def update_data(self) -> None:
        """Recompute the report from the calibrator and refresh everything

        Call this whenever the instrument, picks, parameters, materials,
        or tth distortion of the calibrator change.
        """
        self.update_materials()

        if self.is_structureless:
            material = self.material
            plane_data = material.planeData if material is not None else None
            calibrator = cast('StructurelessCalibrator', self.calibrator)
            self.rings = [(None, x) for x in calibrator.fit_report(plane_data)]
        else:
            self.rings = [
                (name, x)
                for name, calibrator in self.named_calibrators
                if calibrator.type == 'powder'
                for x in calibrator.fit_report()
            ]

        self.update_canvas()

    @property
    def is_visible(self) -> bool:
        return self.ui.isVisible()

    def show(self) -> None:
        self.ui.show()
        self.ui.raise_()
        self.ui.activateWindow()

    def hide(self) -> None:
        self.ui.hide()

    @property
    def is_structureless(self) -> bool:
        # The instrument calibrator has a list of calibrators.
        # The structureless calibrator does not.
        return not hasattr(self.calibrator, 'calibrators')

    @property
    def named_calibrators(self) -> list[tuple[str, Any]]:
        """The calibrators of an instrument calibrator with their names"""
        if self.is_structureless:
            return []

        calibrators = cast('InstrumentCalibrator', self.calibrator).calibrators
        names = self.calibrator_names
        if names is None:
            names = [x.material.name for x in calibrators]

        return list(zip(names, calibrators))

    @property
    def num_powder_calibrators(self) -> int:
        return sum(x.type == 'powder' for _, x in self.named_calibrators)

    @property
    def material_name(self) -> str | None:
        if not self.is_structureless:
            return None

        return self.ui.material.currentData()

    @property
    def material(self) -> Material | None:
        name = self.material_name
        return HexrdConfig().material(name) if name is not None else None

    @property
    def uses_material(self) -> bool:
        """Whether residuals are measured from the hkls of a material"""
        return not self.is_structureless or self.material_name is not None

    @property
    def show_all_detectors(self) -> bool:
        return self.ui.show_all_detectors.isChecked()

    @property
    def det_keys_to_plot(self) -> list[str]:
        if self.show_all_detectors:
            return list(self.calibrator.instr.detectors)
        return [self.ui.detector.currentText()]

    def show_all_detectors_toggled(self) -> None:
        self.update_enable_states()
        self.update_canvas()

    def ring_label(self, ring: RingReport) -> str:
        if ring.index is None:
            # Powder rings are labeled by their hkl
            assert ring.hkl is not None
            return ' '.join(map(str, ring.hkl))

        # Match the "DS ring" numbering in the picks editor
        label = str(ring.index + 1)
        if len(self.calibrator.instr.beam_names) > 1:
            label = f'{ring.xray_source} {label}'
        return label

    def legend_label(self, row: RingRow) -> str:
        if self.num_powder_calibrators > 1:
            return f'{row.group} {row.label}'
        return row.label

    @property
    def ring_rows(self) -> list[RingRow]:
        """The rings that have points on the selected detectors"""
        det_keys = self.det_keys_to_plot
        uses_material = self.uses_material

        rows = []
        for i, (group, ring) in enumerate(self.rings):
            mask = np.isin(ring.detectors, det_keys)
            if not mask.any():
                continue

            row = RingRow(
                group=group,
                label=self.ring_label(ring),
                # Keep the ring colors the same when the detectors change
                color=f'C{i % 10}',
                ring=ring,
                tth=ring.tth[mask],
                eta=ring.eta[mask],
                detectors=ring.detectors[mask],
                reference=ring.material_tth if uses_material else ring.fit_tth,
            )
            rows.append(row)

        return rows

    def update_table(self, rows: list[RingRow]) -> None:
        table = self.ui.table
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            ring = row.ring
            std = row.tth.std()
            hkl = ' '.join(map(str, ring.hkl)) if ring.hkl is not None else ''
            fit_tth = f'{ring.fit_tth:.3f}' if ring.fit_tth is not None else ''
            material_tth = ''
            if ring.material_tth is not None:
                material_tth = f'{ring.material_tth:.3f}'

            offset = ''
            rel_std = ''
            if row.reference is not None:
                offset = f'{row.tth.mean() - row.reference:+.3f}'
                rel_std = f'{std / row.reference:.2e}'

            values = [
                row.group or '',
                row.label,
                str(len(row.tth)),
                # The unique detectors, in order
                ', '.join(dict.fromkeys(row.detectors)),
                hkl,
                fit_tth,
                material_tth,
                f'{row.tth.mean():.3f}',
                offset,
                f'{std:.4f}',
                rel_std,
            ]
            for j, value in enumerate(values):
                table.setItem(i, j, QTableWidgetItem(value))

        hidden_columns = {
            'Overlay': self.num_powder_calibrators < 2,
            # Powder rings are already labeled by their hkl
            'hkl': not (self.is_structureless and self.uses_material),
            'Fit 2θ (°)': not self.is_structureless,
            'hkl 2θ (°)': not self.uses_material,
        }
        for name, hidden in hidden_columns.items():
            table.setColumnHidden(TABLE_COLUMNS.index(name), hidden)

        table.resizeColumnsToContents()

    @property
    def reference_description(self) -> str:
        if self.is_structureless:
            if self.material_name is None:
                return FIT_REFERENCE_LABEL.lower()
            return f'{self.material_name} hkls'

        names = [name for name, x in self.named_calibrators if x.type == 'powder']
        if len(names) == 1:
            return f'{names[0]} hkls'
        return 'hkls of each material'

    def update_canvas(self) -> None:
        # Clear the entire figure, and recreate the subplots each time
        self.fig.clear()

        rows = self.ring_rows
        self.update_table(rows)

        # Rings without a reference cannot be plotted
        rows = [x for x in rows if x.reference is not None]
        if not rows:
            self.fig.text(
                0.5,
                0.5,
                'No rings to show',
                ha='center',
                va='center',
                fontsize=16,
                color='gray',
            )
            self.canvas.draw()
            return

        bounds = self.ui.bounds.value()
        nbins = self.ui.histogram_bins.value()

        self.fig.suptitle(f'Residuals from the {self.reference_description}')

        ax_rel, ax_hist, ax_eta = self.fig.subplots(1, 3)
        diff_label = r'$2\theta_{Meas} - 2\theta_{Ref}$ (degrees)'

        # 1. The relative spread of each ring
        references = np.array([x.reference for x in rows], dtype=float)
        rel_stds = np.array([x.tth.std() for x in rows]) / references
        ax_rel.scatter(references, rel_stds, c=[x.color for x in rows], s=40)
        mean_rel_std = rel_stds.mean()
        ax_rel.axhline(
            mean_rel_std,
            color='red',
            linewidth=3,
            alpha=0.5,
            label=f'Mean: {mean_rel_std:.2e}',
        )
        ax_rel.legend()
        ax_rel.set_ylim(bottom=0)
        ax_rel.ticklabel_format(axis='y', style='sci', scilimits=(-3, 3))
        ax_rel.set_xlabel(r'$2\theta_{Ref}$ (degrees)')
        ax_rel.set_ylabel(r'$\sigma_{2\theta} / 2\theta_{Ref}$')
        ax_rel.set_title('Relative Spread of Each Ring')

        # 2. Histogram of all residuals
        residuals = np.hstack([x.tth - x.reference for x in rows])
        hist_bins = np.linspace(-bounds, bounds, nbins + 1)
        ax_hist.hist(residuals, hist_bins, edgecolor='black', linewidth=0.5)
        ax_hist.set_xlim(-bounds, bounds)
        ax_hist.set_xlabel(diff_label)
        ax_hist.set_ylabel('Number of Points')
        title = 'Residual Histogram'
        num_outside = np.count_nonzero(np.abs(residuals) > bounds)
        if num_outside:
            title += f' ({num_outside} outside bounds)'
        ax_hist.set_title(title)

        # 3. Residuals vs eta, which shows systematic geometry errors
        for row in rows:
            ax_eta.scatter(
                row.eta,
                row.tth - row.reference,
                color=row.color,
                label=self.legend_label(row),
                s=12,
            )
        ax_eta.axhline(0, color='black', linewidth=0.5)
        ax_eta.set_xlim(-180, 180)
        ax_eta.set_ylim(-bounds, bounds)
        ax_eta.set_xlabel(r'$\eta$ (degrees)')
        ax_eta.set_ylabel(diff_label)
        ax_eta.set_title(r'Residual vs $\eta$')
        ax_eta.legend(title='Ring', fontsize='small', ncols=len(rows) // 13 + 1)

        self.canvas.draw()
