import re

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QMenu, QSpinBox,
    QStyledItemDelegate, QTableWidgetItem, QWidget
)

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.overlays.const_chi_overlay import ChiValue
from hexrdgui.tree_views.dict_tree_view import DictTreeItemModel, DictTreeView
from hexrdgui.ui_loader import UiLoader
from hexrdgui.utils import (
    block_signals, euler_angles_to_exp_map, exp_map_to_euler_angles
)
from hexrdgui.utils.const_chi import calc_angles_for_fiber

COLUMNS = {
    'value': 0,
    'hkl': 1,
    'visible': 2,
}


class ConstChiOverlayEditor(QObject):

    def __init__(self, parent=None):
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

        self._overlay = None

        self.visibility_boxes = []

        self.setup_connections()

    def setup_connections(self):
        for w in self.widgets:
            if isinstance(w, (QDoubleSpinBox, QSpinBox)):
                w.valueChanged.connect(self.update_config)
            elif isinstance(w, QCheckBox):
                w.toggled.connect(self.update_config)
            elif isinstance(w, QComboBox):
                w.currentIndexChanged.connect(self.update_config)

        HexrdConfig().euler_angle_convention_changed.connect(
            self.euler_angle_convention_changed)

        self.ui.add_chi_value_row.clicked.connect(
            self.add_chi_value)
        self.chi_table.itemChanged.connect(self.update_config)
        self.chi_table.itemSelectionChanged.connect(self.update_enable_states)

        self.ui.delete_selected_chi_values.clicked.connect(
            self.delete_selected_rows)

        for w in self.fiber_widgets:
            w.valueChanged.connect(self.update_fiber_tree)

        self.fiber_tree.selection_changed.connect(self.update_enable_states)
        self.fiber_tree.add_selected_chi_values.connect(
            self.add_selected_chi_values)

        self.ui.add_selected_chi_values.clicked.connect(
            self.add_selected_chi_values)

    def eventFilter(self, obj, event):
        if obj is self.chi_table:
            return self.chi_table_event_filter(obj, event)

        return False

    def chi_table_event_filter(self, obj, event):
        if isinstance(event, QKeyEvent):
            if event.key() == Qt.Key_Delete:
                self.delete_selected_rows()
                return True

        return False

    @property
    def overlay(self):
        return self._overlay

    @overlay.setter
    def overlay(self, v):
        self._overlay = v
        self.update_gui()

    def update_enable_states(self):
        num_selected = len(self.selected_chi_value_rows)
        self.ui.delete_selected_chi_values.setEnabled(num_selected > 0)

        num_selected = len(self.fiber_tree.selected_rows)
        self.ui.add_selected_chi_values.setEnabled(num_selected > 0)

    def create_visibility_checkbox(self, v):
        cb = QCheckBox(self.chi_table)
        cb.setChecked(v)
        cb.toggled.connect(self.update_config)
        self.visibility_boxes.append(cb)
        return self.create_table_widget(cb)

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.chi_table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def update_gui(self):
        if self.overlay is None:
            return

        with block_signals(*self.widgets):
            self.tvec_gui = self.tvec_config
            self.tilt_gui = self.tilt_config
            self.chi_values_gui = self.chi_values_config

        self.update_tilt_suffixes()
        self.update_fiber_tree()
        self.update_enable_states()

    def update_config(self):
        self.tvec_config = self.tvec_gui
        self.tilt_config = self.tilt_gui
        self.chi_values_config = self.chi_values_gui

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

        # The ConstChiOverlay might sort or remove duplicate chi values.
        # So we should update the GUI in case that happened.
        self.update_gui()

    def euler_angle_convention_changed(self):
        self.update_gui()

    def update_tilt_suffixes(self):
        suffix = '' if HexrdConfig().euler_angle_convention is None else '°'
        for w in self.tilt_widgets:
            w.setSuffix(suffix)

    @property
    def tilt_config(self):
        if self.overlay is None:
            return

        return self.overlay.sample_tilt

    @tilt_config.setter
    def tilt_config(self, v):
        if self.overlay is None:
            return

        self.overlay.sample_tilt = v

    @property
    def tilt_gui(self):
        angles = [w.value() for w in self.tilt_widgets]
        return euler_angles_to_exp_map(angles)

    @tilt_gui.setter
    def tilt_gui(self, v):
        if v is None:
            return

        angles = exp_map_to_euler_angles(v)
        for w, v in zip(self.tilt_widgets, angles):
            w.setValue(v)

    @property
    def tvec_config(self):
        if self.overlay is None:
            return

        return self.overlay.tvec

    @tvec_config.setter
    def tvec_config(self, v):
        if self.overlay is None:
            return

        self.overlay.tvec = v

    @property
    def tvec_gui(self):
        return [w.value() for w in self.tvec_widgets]

    @tvec_gui.setter
    def tvec_gui(self, v):
        if v is None:
            return

        for i, w in enumerate(self.tvec_widgets):
            w.setValue(v[i])

    @property
    def chi_values_config(self):
        if self.overlay is None:
            return

        return self.overlay.chi_values

    @chi_values_config.setter
    def chi_values_config(self, v):
        if self.overlay is None:
            return

        self.overlay.chi_values = v

    @property
    def chi_table(self):
        return self.ui.chi_values

    def clear_table(self):
        table = self.chi_table
        table.clearContents()

        self.visibility_boxes.clear()

    @property
    def chi_values_gui(self):
        results = []
        table = self.chi_table
        for i in range(table.rowCount()):
            results.append(ChiValue(**{
                'value': float(table.item(i, COLUMNS['value']).text()),
                'hkl': table.item(i, COLUMNS['hkl']).text(),
                'visible': self.visibility_boxes[i].isChecked(),
            }))

        return results

    @chi_values_gui.setter
    def chi_values_gui(self, v):
        table = self.chi_table

        with block_signals(table):
            self.clear_table()

            table.setRowCount(len(v))
            for i, chi_value in enumerate(v):
                w = FloatTableItem(chi_value.value)
                table.setItem(i, COLUMNS['value'], w)

                w = QTableWidgetItem(chi_value.hkl)
                w.setTextAlignment(Qt.AlignCenter)
                table.setItem(i, COLUMNS['hkl'], w)

                w = self.create_visibility_checkbox(chi_value.visible)
                table.setCellWidget(i, COLUMNS['visible'], w)

    def add_chi_value(self):
        # Find a unique chi value and add it
        all_values = [x.value for x in self.chi_values_config]
        unique_value = None
        for i in range(180):
            if i not in all_values:
                unique_value = i
                break

        if unique_value is None:
            raise Exception('Unable to create a unique chi value')

        self.add_chi_values([ChiValue(**{
            'value': unique_value,
            'hkl': 'None',
            'visible': True,
        })])

    def add_chi_values(self, v):
        self.chi_values_config = self.chi_values_config + v
        self.update_gui()

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def selected_chi_value_rows(self):
        selected_indexes = self.chi_table.selectionModel().selectedRows()
        return sorted([x.row() for x in selected_indexes])

    def delete_selected_rows(self):
        selected_rows = self.selected_chi_value_rows
        new_values = []
        for i, chi_value in enumerate(self.chi_values_config):
            if i not in selected_rows:
                new_values.append(chi_value)

        self.chi_values_config = new_values
        self.update_gui()

        self.overlay.update_needed = True
        HexrdConfig().overlay_config_changed.emit()

    @property
    def fiber_gui(self):
        return [w.value() for w in self.fiber_widgets]

    @property
    def tilt_widgets(self):
        return [getattr(self.ui, f'tilt_{i}') for i in range(3)]

    @property
    def tvec_widgets(self):
        return [getattr(self.ui, f'tvec_{i}') for i in range(3)]

    @property
    def fiber_widgets(self):
        return [getattr(self.ui, f'fiber_{i}') for i in range(3)]

    @property
    def widgets(self):
        return [
            *self.tilt_widgets,
            *self.tvec_widgets,
        ]

    def update_fiber_tree(self):
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

    def add_selected_chi_values(self):
        self.add_chi_values([{
            'value': x.data(1),
            'hkl': x.parent_item.data(0),
            'visible': True,
        } for x in self.fiber_tree.selected_items])


class FloatTableItem(QTableWidgetItem):
    # Subclass to store the actual float value alongside string version
    DATA_ROLE = Qt.UserRole

    def __init__(self, data):
        string = '{:.10g}'.format(data).replace('e+', 'e')
        string = re.sub(r'e(-?)0*(\d+)', r'e\1\2', string)

        super().__init__(string)

        self.setTextAlignment(Qt.AlignCenter)
        self.setData(self.DATA_ROLE, data)

    @property
    def value(self):
        return self.data(self.DATA_ROLE)

    def __lt__(self, other):
        return self.value < other.value


class CenterDelegate(QStyledItemDelegate):
    # Use this so that the QTableWidget text editor is centered
    def createEditor(self, parent, option, index):
        editor = QStyledItemDelegate.createEditor(self, parent, option, index)
        editor.setAlignment(Qt.AlignCenter)
        return editor


class FiberTreeModel(DictTreeItemModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Override these titles
        self.root_item.set_data(0, 'HKL')
        self.root_item.set_data(1, 'Chi Values')


class FiberTreeView(DictTreeView):

    add_selected_chi_values = Signal()

    def __init__(self, *args, **kwargs):
        kwargs = {
            'model': FiberTreeModel,
            **kwargs,
        }
        super().__init__(*args, **kwargs)

        self.editable = False
        self.lists_resizable = False
        self.set_extended_selection_mode()

    @property
    def config(self):
        return self.model().config

    @config.setter
    def config(self, v):
        self.model().config = v
        self.rebuild_tree()

    def rebuild_tree(self):
        return self.model().rebuild_tree()

    def contextMenuEvent(self, event):
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        selected_items = self.selected_items
        path = tuple(model.path_to_value(item, index.column()))
        parent_element = model.config_val(path[:-1]) if path else None  # noqa
        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator():
            if not actions:
                return
            menu.addSeparator()

        if len(path) == 2 and selected_items:
            # Find the selected items
            add_actions({
                'Add Chi Values': self.add_selected_chi_values.emit,
            })

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
