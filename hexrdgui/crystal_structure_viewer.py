from __future__ import annotations

from functools import partial
import math
from typing import Any

import numpy as np

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
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
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
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


DISPLAY_MODE_SPHERES = 'Spheres'
DISPLAY_MODE_BALL_AND_STICK = 'Ball and stick'

DEFAULT_BACKGROUND_COLOR: Color = (255, 255, 255)
DEFAULT_AXIS_COLORS: dict[str, Color] = {
    'a': (230, 80, 80),
    'b': (80, 170, 95),
    'c': (80, 125, 230),
}
DEFAULT_AXIS_LABELS = {'a': 'a', 'b': 'b', 'c': 'c'}
DEFAULT_AXIS_SIZE = 54.0
DEFAULT_CELL_COLOR: Color = (35, 38, 42)
DEFAULT_CELL_WIDTH = 1.4


class CrystalStructureDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle('Crystal Structure')
        self.resize(980, 680)

        self._atom_colors: dict[str, Color] = {}
        self._atom_radii: dict[str, float] = {}
        self._axis_colors = DEFAULT_AXIS_COLORS.copy()
        self._background_color = DEFAULT_BACKGROUND_COLOR
        self._cell_color = DEFAULT_CELL_COLOR
        self._updating_controls = False

        self.viewer = CrystalStructureWidget(self)
        self.display_mode = QComboBox(self)
        self.materials_combo = QComboBox(self)
        self.radius_scale = QDoubleSpinBox(self)
        self.bond_cutoff_scale = QDoubleSpinBox(self)
        self.stick_radius = QDoubleSpinBox(self)
        self.background_color_button = QPushButton(self)
        self.show_cell = QCheckBox(self)
        self.cell_color_button = QPushButton(self)
        self.cell_width = QDoubleSpinBox(self)
        self.show_axes = QCheckBox(self)
        self.axis_size = QDoubleSpinBox(self)
        self.axis_label_edits: dict[str, QLineEdit] = {}
        self.axis_color_buttons: dict[str, QPushButton] = {}
        self.atom_table = QTableWidget(self)

        self.setup_ui()
        self.setup_connections()
        self.update_materials()

    def setup_ui(self) -> None:
        controls = QWidget(self)
        controls.setMinimumWidth(280)
        controls.setMaximumWidth(340)

        structure_form = QFormLayout()
        structure_form.addRow('Material', self.materials_combo)

        self.display_mode.addItems([DISPLAY_MODE_SPHERES, DISPLAY_MODE_BALL_AND_STICK])
        structure_form.addRow('Display mode', self.display_mode)

        self.background_color_button.setToolTip('Change background color')
        self.update_background_button()
        scene_form = QFormLayout()
        scene_form.addRow('Background', self.background_color_button)

        self.radius_scale.setRange(0.1, 5.0)
        self.radius_scale.setSingleStep(0.1)
        self.radius_scale.setDecimals(2)
        self.radius_scale.setValue(1.0)
        structure_form.addRow('Radius scale', self.radius_scale)

        self.bond_cutoff_scale.setRange(0.5, 2.0)
        self.bond_cutoff_scale.setSingleStep(0.05)
        self.bond_cutoff_scale.setDecimals(2)
        self.bond_cutoff_scale.setValue(1.15)
        structure_form.addRow('Bond tolerance', self.bond_cutoff_scale)

        self.stick_radius.setRange(0.005, 0.5)
        self.stick_radius.setSingleStep(0.005)
        self.stick_radius.setDecimals(3)
        self.stick_radius.setValue(0.055)
        structure_form.addRow('Stick radius', self.stick_radius)

        cell_form = QFormLayout()
        self.show_cell.setChecked(True)
        cell_form.addRow('Show outline', self.show_cell)

        self.cell_color_button.setToolTip('Change unit cell outline color')
        self.update_cell_button()
        cell_form.addRow('Color', self.cell_color_button)

        self.cell_width.setRange(0.25, 8.0)
        self.cell_width.setSingleStep(0.25)
        self.cell_width.setDecimals(2)
        self.cell_width.setValue(DEFAULT_CELL_WIDTH)
        cell_form.addRow('Width', self.cell_width)

        self.show_axes.setChecked(True)
        axes_form = QFormLayout()
        axes_form.addRow('Show axes', self.show_axes)

        self.axis_size.setRange(12.0, 180.0)
        self.axis_size.setSingleStep(4.0)
        self.axis_size.setDecimals(1)
        self.axis_size.setValue(DEFAULT_AXIS_SIZE)
        axes_form.addRow('Arrow size', self.axis_size)

        for axis in ('a', 'b', 'c'):
            axes_form.addRow(f'{axis} axis', self.create_axis_controls(axis))

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
        controls_layout.addWidget(group_box('Structure', structure_form, controls))
        controls_layout.addWidget(group_box('Scene', scene_form, controls))
        controls_layout.addWidget(group_box('Unit Cell', cell_form, controls))
        controls_layout.addWidget(group_box('Axes', axes_form, controls))
        atom_group = QGroupBox('Atom Styles', controls)
        atom_layout = QVBoxLayout(atom_group)
        atom_layout.addWidget(self.atom_table)
        controls_layout.addWidget(atom_group)
        action_group = QGroupBox('Actions', controls)
        action_layout = QVBoxLayout(action_group)
        action_layout.addWidget(reset_view)
        action_layout.addWidget(reset_styles)
        controls_layout.addWidget(action_group)
        controls_layout.addStretch()
        controls_layout.addWidget(buttons)

        layout = QHBoxLayout(self)
        layout.addWidget(self.viewer, stretch=1)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(controls)
        scroll_area.setMinimumWidth(300)
        scroll_area.setMaximumWidth(370)
        layout.addWidget(scroll_area)

    def setup_connections(self) -> None:
        self.materials_combo.currentTextChanged.connect(self.material_changed)
        self.display_mode.currentTextChanged.connect(self.style_changed)
        self.radius_scale.valueChanged.connect(self.style_changed)
        self.bond_cutoff_scale.valueChanged.connect(self.style_changed)
        self.stick_radius.valueChanged.connect(self.render_style_changed)
        self.background_color_button.clicked.connect(self.select_background_color)
        self.show_cell.toggled.connect(self.render_style_changed)
        self.cell_color_button.clicked.connect(self.select_cell_color)
        self.cell_width.valueChanged.connect(self.render_style_changed)
        self.show_axes.toggled.connect(self.render_style_changed)
        self.axis_size.valueChanged.connect(self.render_style_changed)
        for axis, edit in self.axis_label_edits.items():
            edit.textChanged.connect(partial(self.axis_label_changed, axis))
        for axis, button in self.axis_color_buttons.items():
            button.clicked.connect(partial(self.select_axis_color, axis))
        HexrdConfig().materials_dict_modified.connect(self.update_materials)
        HexrdConfig().active_material_changed.connect(self.active_material_changed)
        HexrdConfig().active_material_modified.connect(self.style_changed)

    @property
    def ball_and_stick(self) -> bool:
        return self.display_mode.currentText() == DISPLAY_MODE_BALL_AND_STICK

    def create_axis_controls(self, axis: str) -> QWidget:
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        edit = QLineEdit(DEFAULT_AXIS_LABELS[axis], widget)
        edit.setMaxLength(8)
        self.axis_label_edits[axis] = edit

        button = QPushButton(widget)
        button.setToolTip(f'Change {axis} axis color')
        button.setFixedWidth(44)
        button.setStyleSheet(color_stylesheet(self._axis_colors[axis]))
        self.axis_color_buttons[axis] = button

        layout.addWidget(edit, stretch=1)
        layout.addWidget(button)
        return widget

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

        self.set_default_display_mode()
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
        self.set_default_display_mode()
        self.update_scene(reset_view=True)

    def style_changed(self) -> None:
        if self._updating_controls:
            return

        self.update_scene()

    def reset_styles(self) -> None:
        self._atom_colors.clear()
        self._atom_radii.clear()
        self._axis_colors = DEFAULT_AXIS_COLORS.copy()
        self._background_color = DEFAULT_BACKGROUND_COLOR
        self._cell_color = DEFAULT_CELL_COLOR
        with block_signals(
            self.radius_scale,
            self.bond_cutoff_scale,
            self.stick_radius,
            self.show_cell,
            self.cell_width,
            self.show_axes,
            self.axis_size,
            *self.axis_label_edits.values(),
        ):
            self.radius_scale.setValue(1.0)
            self.bond_cutoff_scale.setValue(1.15)
            self.stick_radius.setValue(0.055)
            self.show_cell.setChecked(True)
            self.cell_width.setValue(DEFAULT_CELL_WIDTH)
            self.show_axes.setChecked(True)
            self.axis_size.setValue(DEFAULT_AXIS_SIZE)
            for axis, edit in self.axis_label_edits.items():
                edit.setText(DEFAULT_AXIS_LABELS[axis])
            for axis, button in self.axis_color_buttons.items():
                button.setStyleSheet(color_stylesheet(self._axis_colors[axis]))
            self.update_background_button()
            self.update_cell_button()
        self.apply_render_options()
        self.viewer.reset_axis_position()
        self.update_scene()

    def render_style_changed(self) -> None:
        self.apply_render_options()

    def apply_render_options(self) -> None:
        labels = {
            axis: edit.text() or axis for axis, edit in self.axis_label_edits.items()
        }
        self.viewer.set_background_color(self._background_color)
        self.viewer.set_cell_options(
            show=self.show_cell.isChecked(),
            color=self._cell_color,
            width=self.cell_width.value(),
        )
        self.viewer.set_axis_options(
            show=self.show_axes.isChecked(),
            size=self.axis_size.value(),
            colors=self._axis_colors,
            labels=labels,
        )
        self.viewer.set_stick_radius(self.stick_radius.value())

    def set_default_display_mode(self) -> None:
        material_name = self.materials_combo.currentText()
        material = HexrdConfig().materials.get(material_name)
        if material is None:
            return

        mode = automatic_display_mode(
            material,
            bond_cutoff_scale=self.bond_cutoff_scale.value(),
        )
        with block_signals(self.display_mode):
            self.display_mode.setCurrentText(mode)

    def select_background_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(*self._background_color), self, 'Background color'
        )
        if not color.isValid():
            return

        self._background_color = color.getRgb()[:3]
        self.update_background_button()
        self.apply_render_options()

    def update_background_button(self) -> None:
        self.background_color_button.setStyleSheet(
            color_stylesheet(self._background_color)
        )

    def select_cell_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(*self._cell_color), self, 'Unit cell color'
        )
        if not color.isValid():
            return

        self._cell_color = color.getRgb()[:3]
        self.update_cell_button()
        self.apply_render_options()

    def update_cell_button(self) -> None:
        self.cell_color_button.setStyleSheet(color_stylesheet(self._cell_color))

    def select_axis_color(self, axis: str) -> None:
        color = QColorDialog.getColor(
            QColor(*self._axis_colors[axis]), self, f'{axis} axis color'
        )
        if not color.isValid():
            return

        self._axis_colors[axis] = color.getRgb()[:3]
        self.axis_color_buttons[axis].setStyleSheet(
            color_stylesheet(self._axis_colors[axis])
        )
        self.apply_render_options()

    def axis_label_changed(self, axis: str, text: str) -> None:
        self.apply_render_options()

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
        self.apply_render_options()
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
        self.background_color = QColor(*DEFAULT_BACKGROUND_COLOR)
        self.show_cell = True
        self.cell_color = QColor(*DEFAULT_CELL_COLOR)
        self.cell_width = DEFAULT_CELL_WIDTH
        self.show_axes = True
        self.axis_size = DEFAULT_AXIS_SIZE
        self.axis_offset = self.default_axis_offset()
        self.axis_colors = {
            axis: QColor(*color) for axis, color in DEFAULT_AXIS_COLORS.items()
        }
        self.axis_labels = DEFAULT_AXIS_LABELS.copy()
        self._dragging_axes = False
        self._axis_position_custom = False

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

    def set_background_color(self, color: Color) -> None:
        self.background_color = QColor(*color)
        self.update()

    def set_cell_options(self, *, show: bool, color: Color, width: float) -> None:
        self.show_cell = show
        self.cell_color = QColor(*color)
        self.cell_width = width
        self.update()

    def set_axis_options(
        self,
        *,
        show: bool,
        size: float,
        colors: dict[str, Color],
        labels: dict[str, str],
    ) -> None:
        self.show_axes = show
        self.axis_size = size
        self.axis_colors = {axis: QColor(*color) for axis, color in colors.items()}
        self.axis_labels = labels.copy()
        if not self._axis_position_custom:
            self.axis_offset = self.default_axis_offset()
        self.update()

    def default_axis_offset(self) -> QPointF:
        margin = max(36.0, self.axis_size * 1.05)
        return QPointF(margin, margin)

    def reset_axis_position(self) -> None:
        self._axis_position_custom = False
        self.axis_offset = self.default_axis_offset()
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
        painter.fillRect(self.rect(), self.background_color)

        if self.scene is None:
            painter.setPen(foreground_color_for_background(self.background_color))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                'No crystal structure available',
            )
            painter.end()
            return

        projected = self.project_scene()
        if self.show_cell:
            self.draw_cell(painter, projected)
        if self.ball_and_stick:
            self.draw_bonds(painter, projected)
        self.draw_atoms(painter, projected)
        if self.show_axes:
            self.draw_axes(painter)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_pos = event.position().toPoint()
        self._last_button = event.button()
        self._dragging_axes = (
            event.button() == Qt.MouseButton.LeftButton
            and self.show_axes
            and self.axis_bounds().contains(event.position())
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_pos is None:
            return

        pos = event.position().toPoint()
        delta = pos - self._last_pos
        self._last_pos = pos

        if self._dragging_axes:
            self.axis_offset += QPointF(delta.x(), -delta.y())
            self.axis_offset = self.clamped_axis_offset(self.axis_offset)
            self._axis_position_custom = True
            self.update()
            return

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
        self._dragging_axes = False

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
        base_color = self.cell_color
        pen = QPen(
            QColor(base_color.red(), base_color.green(), base_color.blue(), 180),
            self.cell_width,
        )
        painter.setPen(pen)

        for i1, i2 in self.scene.cell_edges:
            p1 = QPointF(*screen[i1])
            p2 = QPointF(*screen[i2])
            avg_depth = (depth[i1] + depth[i2]) / 2.0
            alpha = 145 + int(65 * normalized_depth(avg_depth, self.scene.extent))
            pen.setColor(
                QColor(base_color.red(), base_color.green(), base_color.blue(), alpha)
            )
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
        origin = self.axis_origin()
        axes = np.eye(3) @ rotation_matrix(self.rotation_x, self.rotation_y).T

        for vector, axis in zip(axes, ('a', 'b', 'c')):
            end = origin + QPointF(
                vector[0] * self.axis_size,
                -vector[1] * self.axis_size,
            )
            color = self.axis_colors.get(axis, QColor(*DEFAULT_AXIS_COLORS[axis]))
            pen = QPen(color, max(2.0, self.axis_size * 0.045))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(origin, end)
            self.draw_axis_arrowhead(painter, origin, end, color)
            painter.drawText(end + QPointF(6.0, -6.0), self.axis_labels.get(axis, axis))

    def draw_axis_arrowhead(
        self,
        painter: QPainter,
        origin: QPointF,
        end: QPointF,
        color: QColor,
    ) -> None:
        direction = end - origin
        length = math.hypot(direction.x(), direction.y())
        if length <= 0:
            return

        unit = QPointF(direction.x() / length, direction.y() / length)
        normal = QPointF(-unit.y(), unit.x())
        arrow_length = max(8.0, self.axis_size * 0.18)
        arrow_width = arrow_length * 0.45
        p1 = end - unit * arrow_length + normal * arrow_width
        p2 = end - unit * arrow_length - normal * arrow_width

        pen = QPen(color, max(2.0, self.axis_size * 0.04))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(end, p1)
        painter.drawLine(end, p2)

    def axis_origin(self) -> QPointF:
        return QPointF(self.axis_offset.x(), self.height() - self.axis_offset.y())

    def axis_endpoints(self) -> list[QPointF]:
        origin = self.axis_origin()
        axes = np.eye(3) @ rotation_matrix(self.rotation_x, self.rotation_y).T
        return [
            origin + QPointF(vector[0] * self.axis_size, -vector[1] * self.axis_size)
            for vector in axes
        ]

    def axis_bounds(self) -> QRectF:
        origin = self.axis_origin()
        points = [origin, *self.axis_endpoints()]
        min_x = min(point.x() for point in points)
        max_x = max(point.x() for point in points)
        min_y = min(point.y() for point in points)
        max_y = max(point.y() for point in points)
        padding = max(18.0, self.axis_size * 0.28)
        return QRectF(
            QPointF(min_x - padding, min_y - padding),
            QPointF(max_x + padding, max_y + padding),
        )

    def clamped_axis_offset(self, offset: QPointF) -> QPointF:
        padding = max(12.0, self.axis_size * 0.2)
        return QPointF(
            min(max(offset.x(), padding), max(padding, self.width() - padding)),
            min(max(offset.y(), padding), max(padding, self.height() - padding)),
        )


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


def automatic_display_mode(material: Any, *, bond_cutoff_scale: float = 1.15) -> str:
    scene = crystal_structure_scene(
        material,
        include_bonds=True,
        bond_cutoff_scale=bond_cutoff_scale,
    )
    return DISPLAY_MODE_BALL_AND_STICK if scene.bonds else DISPLAY_MODE_SPHERES


def foreground_color_for_background(color: QColor) -> QColor:
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor(35, 38, 42) if luminance > 140 else QColor(220, 225, 232)


def group_box(title: str, layout: QFormLayout, parent: QWidget) -> QGroupBox:
    box = QGroupBox(title, parent)
    box.setLayout(layout)
    return box


def color_stylesheet(color: Color) -> str:
    r, g, b = color
    return f'background-color: rgb({r}, {g}, {b});'
