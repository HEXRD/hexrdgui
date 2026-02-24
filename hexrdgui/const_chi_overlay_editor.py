from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import numpy as np

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QContextMenuEvent, QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QMenu,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

if TYPE_CHECKING:
    from hexrdgui.overlays.const_chi_overlay import (
        ConstChiOverlay,
    )

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays.const_chi_overlay import ChiValue
from hexrdgui.tree_views.dict_tree_view import DictTreeItemModel, DictTreeView
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import (
    block_signals,
    euler_angles_to_exp_map,
    exp_map_to_euler_angles,
)
from hexrdgui.utils.const_chi import calc_angles_for_fiber

COLUMNS = {
    'value': 0,
    'hkl': 1,
    'visible': 2,
}


class ConstChiOverlayEditor(QObject):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('const_chi_overlay_editor.ui', parent)

        self.chi_table.setItemDelegate(CenterDelegate())

        self.fiber_tree = FiberTreeView({}, parent=self.ui)
        self.ui.fiber_tree_layout.addWidget(self.fiber_tree)

        self.chi_table.installEventFilter(self)

        # These are not used currently, so just hide them until they are used.
        # FIXME: remove this once these are supported.
        self.ui.tvec_label.hide()
        for w in self.tvec_widgets:
            w.hide()

        self._overlay: ConstChiOverlay | None = None

        self.visibility_boxes: list[QCheckBox] = []

        self.setup_connections()

    def setup_connections(self) -> None:
        for w in self.widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update_config)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed
        )
        HexrdConfig().sample_tilt_modified.connect(self.update_gui)

        self.ui.add_chi_value_row.clicked.connect(self.add_chi_value)
        self.chi_table.itemChanged.connect(self.update_config)
        self.chi_table.itemSelectionChanged.connect(self.update_enable_states)

        self.ui.delete_selected_chi_values.clicked.connect(self.delete_selected_rows)

        for w in self.fiber_widgets:
            w.valueChanged.connect(self.update_fiber_tree)

        self.fiber_tree.selection_changed.connect(self.update_enable_states)
        self.fiber_tree.add_selected_chi_values.connect(self.add_selected_chi_values)

        self.ui.add_selected_chi_values.clicked.connect(self.add_selected_chi_values)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.chi_table:
            return self.chi_table_event_filter(obj, event)

        return False

    def chi_table_event_filter(self, obj: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Delete:
                self.delete_selected_rows()
                return True

        return False

    @property
    def overlay(self) -> ConstChiOverlay | None:
        return self._overlay

    @overlay.setter
    def overlay(self, v: ConstChiOverlay) -> None:
        self._overlay = v
        self.update_gui()

    def update_enable_states(self) -> None:
        num_selected = len(self.selected_chi_value_rows)
        self.ui.delete_selected_chi_values.setEnabled(num_selected > 0)

        num_selected = len(self.fiber_tree.selected_rows)
        self.ui.add_selected_chi_values.setEnabled(num_selected > 0)

    def create_visibility_checkbox(self, v: bool) -> QWidget:
        cb = QCheckBox(self.chi_table)
        cb.setChecked(v)
        cb.toggled.connect(self.update_config)
        self.visibility_boxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w: QWidget) -> QWidget:
        # These are required to center the widget...
        tw = QWidget(self.chi_table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def update_gui(self) -> None:
        if self.overlay is None:
            return

        with block_signals(*self.widgets):
            self.tvec_gui = self.tvec_config
            self.tilt_gui = self.tilt_config
            self.chi_values_gui = self.chi_values_config

        self.update_tilt_suffixes()
        self.update_fiber_tree()
        self.update_enable_states()

    def update_config(self) -> None:
        self.tvec_config = self.tvec_gui
        self.tilt_config = self.tilt_gui
        self.chi_values_config = self.chi_values_gui

        assert self.overlay is not None
        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

        # The ConstChiOverlay might sort or remove duplicate chi values.
        # So we should update the GUI in case that happened.
        # We need to do this on the next iteration of the event loop
        # to avoid the following error message:
        # QAbstractItemView::closeEditor called with an editor that does
        # not belong to this view
        QTimer.singleShot(0, self.update_gui)

    def euler_angle_convention_changed(self) -> None:
        self.update_gui()

    def update_tilt_suffixes(self) -> None:
        suffix = '' if HexrdConfig().euler_angle_convention is None else '°'
        for w in self.tilt_widgets:
            w.setSuffix(suffix)

    @property
    def tilt_config(self) -> Any:
        if self.overlay is None:
            return None

        return self.overlay.sample_tilt

    @tilt_config.setter
    def tilt_config(self, v: Any) -> None:
        if self.overlay is None:
            return

        self.overlay.sample_tilt = v

    @property
    def tilt_gui(self) -> Any:
        angles = [w.value() for w in self.tilt_widgets]
        return euler_angles_to_exp_map(angles)

    @tilt_gui.setter
    def tilt_gui(self, v: Any) -> None:
        if v is None:
            return

        angles = exp_map_to_euler_angles(v)
        for w, v in zip(self.tilt_widgets, angles):
            w.setValue(v)

    @property
    def tvec_config(self) -> np.ndarray | None:
        if self.overlay is None:
            return None

        return self.overlay.tvec

    @tvec_config.setter
    def tvec_config(self, v: list[float] | np.ndarray | None) -> None:
        if self.overlay is None:
            return

        self.overlay.tvec = v

    @property
    def tvec_gui(self) -> list[float]:
        return [w.value() for w in self.tvec_widgets]

    @tvec_gui.setter
    def tvec_gui(self, v: np.ndarray | None) -> None:
        if v is None:
            return

        for i, w in enumerate(self.tvec_widgets):
            w.setValue(v[i])

    @property
    def chi_values_config(self) -> list[ChiValue]:
        if self.overlay is None:
            return []

        return self.overlay.chi_values

    @chi_values_config.setter
    def chi_values_config(self, v: list[Any]) -> None:
        if self.overlay is None:
            return

        self.overlay.chi_values = v

    @property
    def chi_table(self) -> QTableWidget:
        return self.ui.chi_values

    def clear_table(self) -> None:
        table = self.chi_table
        table.clearContents()

        self.visibility_boxes.clear()

    @property
    def chi_values_gui(self) -> list[ChiValue]:
        results = []
        table = self.chi_table
        for i in range(table.rowCount()):
            results.append(
                ChiValue(
                    value=float(table.item(i, COLUMNS['value']).text()),  # type: ignore[union-attr]
                    hkl=table.item(i, COLUMNS['hkl']).text(),  # type: ignore[union-attr]
                    visible=self.visibility_boxes[i].isChecked(),
                )
            )

        return results

    @chi_values_gui.setter
    def chi_values_gui(self, v: list[ChiValue]) -> None:
        table = self.chi_table

        with block_signals(table):
            self.clear_table()

            table.setRowCount(len(v))
            for i, chi_value in enumerate(v):
                w: QTableWidgetItem = FloatTableItem(chi_value.value)
                table.setItem(i, COLUMNS['value'], w)

                w = QTableWidgetItem(chi_value.hkl)
                w.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, COLUMNS['hkl'], w)

                cb_w = self.create_visibility_checkbox(chi_value.visible)
                table.setCellWidget(i, COLUMNS['visible'], cb_w)

    def add_chi_value(self) -> None:
        # Find a unique chi value and add it
        all_values = [x.value for x in self.chi_values_config]
        unique_value = None
        for i in range(180):
            if i not in all_values:
                unique_value = i
                break

        if unique_value is None:
            raise Exception('Unable to create a unique chi value')

        self.add_chi_values(
            [
                ChiValue(
                    value=unique_value,
                    hkl='None',
                    visible=True,
                )
            ]
        )

    def add_chi_values(self, v: list[Any]) -> None:
        self.chi_values_config = self.chi_values_config + v
        self.update_gui()

        assert self.overlay is not None
        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def selected_chi_value_rows(self) -> list[int]:
        selected_indexes = self.chi_table.selectionModel().selectedRows()
        return sorted([x.row() for x in selected_indexes])

    def delete_selected_rows(self) -> None:
        selected_rows = self.selected_chi_value_rows
        new_values = []
        for i, chi_value in enumerate(self.chi_values_config):
            if i not in selected_rows:
                new_values.append(chi_value)

        self.chi_values_config = new_values
        self.update_gui()

        assert self.overlay is not None
        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def fiber_gui(self) -> list[float]:
        return [w.value() for w in self.fiber_widgets]

    @property
    def tilt_widgets(self) -> list[QDoubleSpinBox]:
        return [getattr(self.ui, f'tilt_{i}') for i in range(3)]

    @property
    def tvec_widgets(self) -> list[QDoubleSpinBox]:
        return [getattr(self.ui, f'tvec_{i}') for i in range(3)]

    @property
    def fiber_widgets(self) -> list[QDoubleSpinBox]:
        return [getattr(self.ui, f'fiber_{i}') for i in range(3)]

    @property
    def widgets(self) -> list[QDoubleSpinBox]:
        return [
            *self.tilt_widgets,
            *self.tvec_widgets,
        ]

    def update_fiber_tree(self) -> None:
        # First, clear it
        self.fiber_tree.config = {}
        if self.overlay is None:
            return

        material = self.overlay.material
        fiber_values = self.fiber_gui

        if fiber_values == [0, 0, 0]:
            # All zeros is invalid. Just return.
            return

        result = calc_angles_for_fiber(material, fiber_values)
        # Convert numpy arrays to lists
        result = {k: v.tolist() for k, v in result.items()}

        self.fiber_tree.config = result
        self.fiber_tree.expand_rows(rows=[0, 1, 2])

    def add_selected_chi_values(self) -> None:
        values: list[Any] = []
        for x in self.fiber_tree.selected_items:
            assert x.parent_item is not None
            values.append(
                {
                    'value': x.data(1),
                    'hkl': x.parent_item.data(0),
                    'visible': True,
                }
            )
        self.add_chi_values(values)


class FloatTableItem(QTableWidgetItem):
    # Subclass to store the actual float value alongside string version
    DATA_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, data: float) -> None:
        string = '{:.10g}'.format(data).replace('e+', 'e')
        string = re.sub(r'e(-?)0*(\d+)', r'e\1\2', string)

        super().__init__(string)

        self.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setData(self.DATA_ROLE, data)

    @property
    def value(self) -> float:
        return self.data(self.DATA_ROLE)

    def __lt__(self, other: 'FloatTableItem') -> bool:  # type: ignore[override]
        return self.value < other.value


class CenterDelegate(QStyledItemDelegate):
    # Use this so that the QTableWidget text editor is centered
    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        editor = QStyledItemDelegate.createEditor(self, parent, option, index)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)  # type: ignore[attr-defined]
        return editor


class FiberTreeModel(DictTreeItemModel):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Override these titles
        self.root_item.set_data(0, 'HKL')
        self.root_item.set_data(1, 'Chi Values')


class FiberTreeView(DictTreeView):

    add_selected_chi_values = Signal()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs = {
            'model': FiberTreeModel,
            **kwargs,
        }
        super().__init__(*args, **kwargs)

        self.editable = False
        self.lists_resizable = False
        self.set_extended_selection_mode()

    @property
    def config(self) -> dict[str, Any]:
        return self.model().config

    @config.setter
    def config(self, v: dict[str, Any]) -> None:
        self.model().config = v
        self.rebuild_tree()

    def rebuild_tree(self) -> None:
        return self.model().rebuild_tree()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        selected_items = self.selected_items
        path = tuple(model.path_to_value(item, index.column()))
        parent_element = model.config_val(path[:-1]) if path else None  # type: ignore[arg-type]  # noqa
        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict) -> None:
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator() -> None:
            if not actions:
                return
            menu.addSeparator()

        if len(path) == 2 and selected_items:
            # Find the selected items
            add_actions(
                {
                    'Add Chi Values': self.add_selected_chi_values.emit,
                }
            )

        if not actions:
            # No context menu
            return super().contextMenuEvent(event)

        # Open up the context menu
        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return super().contextMenuEvent(event)

        # Run the function for the action that was chosen
        actions[action_chosen]()

        return super().contextMenuEvent(event)
