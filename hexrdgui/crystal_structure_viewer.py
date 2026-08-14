from __future__ import annotations

from functools import partial
import math
from typing import Any

import numpy as np

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hexrdgui.crystal_structure import (
    Color,
    CrystalAtom,
    CrystalStructureScene,
    crystal_structure_scene,
)
from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.utils import block_signals


class CrystalStructureDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle('Crystal Structure')
        self.resize(980, 680)

        self._atom_colors: dict[str, Color] = {}
        self._atom_radii: dict[str, float] = {}
        self._updating_controls = False

        self.viewer = CrystalStructureWidget(self)
        self.display_mode = QComboBox(self)
        self.materials_combo = QComboBox(self)
        self.radius_scale = QDoubleSpinBox(self)
        self.bond_cutoff_scale = QDoubleSpinBox(self)
        self.stick_radius = QDoubleSpinBox(self)
        self.atom_table = QTableWidget(self)

        self.setup_ui()
        self.setup_connections()
        self.update_materials()

    def setup_ui(self) -> None:
        controls = QWidget(self)
        controls.setMinimumWidth(280)
        controls.setMaximumWidth(340)

        form = QFormLayout()
        form.addRow('Material', self.materials_combo)

        self.display_mode.addItems(['Spheres', 'Ball and stick'])
        form.addRow('Display mode', self.display_mode)

        self.radius_scale.setRange(0.1, 5.0)
        self.radius_scale.setSingleStep(0.1)
        self.radius_scale.setDecimals(2)
        self.radius_scale.setValue(1.0)
        form.addRow('Radius scale', self.radius_scale)

        self.bond_cutoff_scale.setRange(0.5, 2.0)
        self.bond_cutoff_scale.setSingleStep(0.05)
        self.bond_cutoff_scale.setDecimals(2)
        self.bond_cutoff_scale.setValue(1.15)
        form.addRow('Bond tolerance', self.bond_cutoff_scale)

        self.stick_radius.setRange(0.005, 0.5)
        self.stick_radius.setSingleStep(0.005)
        self.stick_radius.setDecimals(3)
        self.stick_radius.setValue(0.055)
        form.addRow('Stick radius', self.stick_radius)

        self.atom_table.setColumnCount(3)
        self.atom_table.setHorizontalHeaderLabels(['Atom', 'Color', 'Radius'])
        self.atom_table.verticalHeader().hide()
        self.atom_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.atom_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.atom_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.atom_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.atom_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )

        reset_view = QPushButton('Reset View', self)
        reset_view.clicked.connect(self.viewer.reset_view)

        reset_styles = QPushButton('Reset Styles', self)
        reset_styles.clicked.connect(self.reset_styles)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)

        controls_layout = QVBoxLayout(controls)
        controls_layout.addLayout(form)
        controls_layout.addWidget(QLabel('Atom styles', controls))
        controls_layout.addWidget(self.atom_table)
        controls_layout.addWidget(reset_view)
        controls_layout.addWidget(reset_styles)
        controls_layout.addStretch()
        controls_layout.addWidget(buttons)

        layout = QHBoxLayout(self)
        layout.addWidget(self.viewer, stretch=1)
        layout.addWidget(controls)

    def setup_connections(self) -> None:
        self.materials_combo.currentTextChanged.connect(self.material_changed)
        self.display_mode.currentTextChanged.connect(self.style_changed)
        self.radius_scale.valueChanged.connect(self.style_changed)
        self.bond_cutoff_scale.valueChanged.connect(self.style_changed)
        self.stick_radius.valueChanged.connect(self.render_style_changed)
        HexrdConfig().materials_dict_modified.connect(self.update_materials)
        HexrdConfig().active_material_changed.connect(self.active_material_changed)
        HexrdConfig().active_material_modified.connect(self.style_changed)

    @property
    def ball_and_stick(self) -> bool:
        return self.display_mode.currentText() == 'Ball and stick'

    def update_materials(self) -> None:
        material_names = list(HexrdConfig().materials)
        current_name = self.materials_combo.currentText()
        active_name = HexrdConfig().active_material_name
        selected_name = current_name if current_name in material_names else active_name

        with block_signals(self.materials_combo):
            self.materials_combo.clear()
            self.materials_combo.addItems(material_names)
            if selected_name in material_names:
                self.materials_combo.setCurrentText(selected_name)

        self.update_scene(reset_view=True)

    def active_material_changed(self) -> None:
        active_name = HexrdConfig().active_material_name
        if active_name is None:
            return

        if self.materials_combo.currentText() != active_name:
            self.materials_combo.setCurrentText(active_name)
        else:
            self.update_scene(reset_view=True)

    def material_changed(self) -> None:
        self._atom_colors.clear()
        self._atom_radii.clear()
        self.update_scene(reset_view=True)

    def style_changed(self) -> None:
        if self._updating_controls:
            return

        self.update_scene()

    def reset_styles(self) -> None:
        self._atom_colors.clear()
        self._atom_radii.clear()
        with block_signals(
            self.radius_scale,
            self.bond_cutoff_scale,
            self.stick_radius,
        ):
            self.radius_scale.setValue(1.0)
            self.bond_cutoff_scale.setValue(1.15)
            self.stick_radius.setValue(0.055)
        self.update_scene()

    def render_style_changed(self) -> None:
        self.viewer.set_stick_radius(self.stick_radius.value())

    def update_scene(self, *, reset_view: bool = False) -> None:
        material_name = self.materials_combo.currentText()
        material = HexrdConfig().materials.get(material_name)
        if material is None:
            self.viewer.set_scene(None)
            self.update_atom_table(())
            return

        try:
            scene = crystal_structure_scene(
                material,
                atom_colors=self._atom_colors,
                atom_radii=self._atom_radii,
                radius_scale=self.radius_scale.value(),
                include_bonds=self.ball_and_stick,
                bond_cutoff_scale=self.bond_cutoff_scale.value(),
            )
        except Exception as e:
            self.viewer.set_scene(None)
            QMessageBox.warning(self, 'HEXRD', str(e))
            return

        self.viewer.set_ball_and_stick(self.ball_and_stick)
        self.viewer.set_stick_radius(self.stick_radius.value())
        self.viewer.set_scene(scene, reset_view=reset_view)
        self.update_atom_table(scene.atoms)

    def update_atom_table(self, atoms: tuple[CrystalAtom, ...]) -> None:
        by_symbol: dict[str, CrystalAtom] = {}
        for atom in atoms:
            by_symbol.setdefault(atom.symbol, atom)

        self._updating_controls = True
        try:
            self.atom_table.setRowCount(len(by_symbol))
            for row, symbol in enumerate(sorted(by_symbol)):
                atom = by_symbol[symbol]
                symbol_item = QTableWidgetItem(symbol)
                symbol_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.atom_table.setItem(row, 0, symbol_item)

                color_button = QPushButton(self.atom_table)
                color_button.setToolTip(f'Change {symbol} color')
                color_button.setStyleSheet(color_stylesheet(atom.style.color))
                color_button.clicked.connect(partial(self.select_color, symbol))
                self.atom_table.setCellWidget(row, 1, color_button)

                radius = QDoubleSpinBox(self.atom_table)
                radius.setRange(0.01, 5.0)
                radius.setDecimals(3)
                radius.setSingleStep(0.025)
                radius.setValue(atom.style.radius)
                radius.valueChanged.connect(partial(self.set_atom_radius, symbol))
                self.atom_table.setCellWidget(row, 2, radius)

            self.atom_table.resizeRowsToContents()
        finally:
            self._updating_controls = False

    def select_color(self, symbol: str) -> None:
        current = self._atom_colors.get(symbol)
        if current is None:
            atoms = self.viewer.scene.atoms if self.viewer.scene else ()
            atom = next((x for x in atoms if x.symbol == symbol), None)
            current = atom.style.color if atom else (255, 255, 255)

        color = QColorDialog.getColor(QColor(*current), self, f'{symbol} color')
        if not color.isValid():
            return

        self._atom_colors[symbol] = color.getRgb()[:3]
        self.update_scene()

    def set_atom_radius(self, symbol: str, radius: float) -> None:
        if self._updating_controls:
            return

        self._atom_radii[symbol] = radius
        self.update_scene()


class CrystalStructureWidget(QOpenGLWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.scene: CrystalStructureScene | None = None
        self.rotation_x = 25.0
        self.rotation_y = -35.0
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        self._last_pos: QPoint | None = None
        self._last_button: Qt.MouseButton | None = None
        self.ball_and_stick = False
        self.stick_radius = 0.055

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(680, 560)

    def set_scene(
        self,
        scene: CrystalStructureScene | None,
        *,
        reset_view: bool = False,
    ) -> None:
        self.scene = scene
        if reset_view:
            self.reset_view(update=False)
        self.update()

    def set_ball_and_stick(self, enabled: bool) -> None:
        self.ball_and_stick = enabled
        self.update()

    def set_stick_radius(self, radius: float) -> None:
        self.stick_radius = radius
        self.update()

    def reset_view(self, *, update: bool = True) -> None:
        self.rotation_x = 25.0
        self.rotation_y = -35.0
        self.zoom = 1.0
        self.pan = QPointF(0.0, 0.0)
        if update:
            self.update()

    def paintGL(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(24, 27, 31))

        if self.scene is None:
            painter.setPen(QColor(210, 214, 220))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                'No crystal structure available',
            )
            painter.end()
            return

        projected = self.project_scene()
        self.draw_cell(painter, projected)
        if self.ball_and_stick:
            self.draw_bonds(painter, projected)
        self.draw_atoms(painter, projected)
        self.draw_axes(painter)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_pos = event.position().toPoint()
        self._last_button = event.button()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_pos is None:
            return

        pos = event.position().toPoint()
        delta = pos - self._last_pos
        self._last_pos = pos

        pan_requested = self._last_button in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ) or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if pan_requested:
            self.pan += QPointF(delta)
        elif self._last_button == Qt.MouseButton.LeftButton:
            self.rotation_y += delta.x() * 0.5
            self.rotation_x += delta.y() * 0.5

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._last_pos = None
        self._last_button = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        angle = event.angleDelta().y()
        if angle == 0:
            return

        factor = 1.0015**angle
        self.zoom = min(max(self.zoom * factor, 0.1), 30.0)
        self.update()

    def project_scene(self) -> dict[str, Any]:
        assert self.scene is not None

        points = self.scene.points
        centered = points - self.scene.center
        rotated = centered @ rotation_matrix(self.rotation_x, self.rotation_y).T

        scale = self.zoom * min(self.width(), self.height())
        scale /= 2.4 * self.scene.extent

        screen = np.empty((len(rotated), 2), dtype=float)
        screen[:, 0] = rotated[:, 0] * scale + self.width() / 2.0 + self.pan.x()
        screen[:, 1] = -rotated[:, 1] * scale + self.height() / 2.0 + self.pan.y()

        return {
            'screen': screen,
            'depth': rotated[:, 2],
            'scale': scale,
        }

    def draw_cell(self, painter: QPainter, projected: dict[str, Any]) -> None:
        assert self.scene is not None

        screen = projected['screen']
        depth = projected['depth']
        pen = QPen(QColor(185, 195, 210, 190), 1.4)
        painter.setPen(pen)

        for i1, i2 in self.scene.cell_edges:
            p1 = QPointF(*screen[i1])
            p2 = QPointF(*screen[i2])
            avg_depth = (depth[i1] + depth[i2]) / 2.0
            alpha = 145 + int(65 * normalized_depth(avg_depth, self.scene.extent))
            pen.setColor(QColor(185, 195, 210, alpha))
            painter.setPen(pen)
            painter.drawLine(p1, p2)

    def draw_atoms(self, painter: QPainter, projected: dict[str, Any]) -> None:
        assert self.scene is not None

        atom_offset = len(self.scene.cell_vertices)
        screen = projected['screen']
        depth = projected['depth']
        scale = projected['scale']

        atom_indices = range(len(self.scene.atoms))
        ordered_indices = sorted(atom_indices, key=lambda i: depth[atom_offset + i])

        for atom_index in ordered_indices:
            atom = self.scene.atoms[atom_index]
            point_index = atom_offset + atom_index
            radius_multiplier = 0.45 if self.ball_and_stick else 1.0
            radius = max(3.0, atom.style.radius * scale * radius_multiplier)
            center = QPointF(*screen[point_index])
            self.draw_sphere(painter, center, radius, atom)

    def draw_bonds(self, painter: QPainter, projected: dict[str, Any]) -> None:
        assert self.scene is not None

        atom_offset = len(self.scene.cell_vertices)
        screen = projected['screen']
        depth = projected['depth']
        scale = projected['scale']
        width = max(1.5, self.stick_radius * scale)

        bonds = sorted(
            self.scene.bonds,
            key=lambda bond: (
                (
                    depth[atom_offset + bond.atom1_index]
                    + depth[atom_offset + bond.atom2_index]
                )
                / 2.0
            ),
        )
        pen = QPen()
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        for bond in bonds:
            atom1 = self.scene.atoms[bond.atom1_index]
            atom2 = self.scene.atoms[bond.atom2_index]
            p1 = QPointF(*screen[atom_offset + bond.atom1_index])
            p2 = QPointF(*screen[atom_offset + bond.atom2_index])
            middle = QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0)

            pen.setColor(QColor(*atom1.style.color))
            painter.setPen(pen)
            painter.drawLine(p1, middle)

            pen.setColor(QColor(*atom2.style.color))
            painter.setPen(pen)
            painter.drawLine(middle, p2)

    def draw_sphere(
        self,
        painter: QPainter,
        center: QPointF,
        radius: float,
        atom: CrystalAtom,
    ) -> None:
        color = QColor(*atom.style.color)
        color.setAlphaF(min(max(atom.occupancy, 0.2), 1.0))

        highlight = color.lighter(175)
        shadow = color.darker(165)
        gradient = QRadialGradient(
            center - QPointF(radius * 0.35, radius * 0.35),
            radius * 1.35,
        )
        gradient.setColorAt(0.0, highlight)
        gradient.setColorAt(0.45, color)
        gradient.setColorAt(1.0, shadow)

        painter.setPen(QPen(QColor(0, 0, 0, 115), 0.8))
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)

    def draw_axes(self, painter: QPainter) -> None:
        origin = QPointF(44.0, self.height() - 42.0)
        axes = np.eye(3) @ rotation_matrix(self.rotation_x, self.rotation_y).T
        labels = [
            ('a', QColor(230, 80, 80)),
            ('b', QColor(80, 190, 100)),
            ('c', QColor(90, 140, 240)),
        ]

        for axis, (label, color) in zip(axes, labels):
            end = origin + QPointF(axis[0] * 28.0, -axis[1] * 28.0)
            painter.setPen(QPen(color, 2.0))
            painter.drawLine(origin, end)
            painter.drawText(end + QPointF(4.0, -4.0), label)


def rotation_matrix(rotation_x: float, rotation_y: float) -> np.ndarray:
    rx = math.radians(rotation_x)
    ry = math.radians(rotation_y)

    cos_x, sin_x = math.cos(rx), math.sin(rx)
    cos_y, sin_y = math.cos(ry), math.sin(ry)

    mx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, cos_x, -sin_x],
            [0.0, sin_x, cos_x],
        ]
    )
    my = np.array(
        [
            [cos_y, 0.0, sin_y],
            [0.0, 1.0, 0.0],
            [-sin_y, 0.0, cos_y],
        ]
    )

    return my @ mx


def normalized_depth(depth: float, extent: float) -> float:
    return min(max((depth / extent + 1.0) / 2.0, 0.0), 1.0)


def color_stylesheet(color: Color) -> str:
    r, g, b = color
    return f'background-color: rgb({r}, {g}, {b});'
