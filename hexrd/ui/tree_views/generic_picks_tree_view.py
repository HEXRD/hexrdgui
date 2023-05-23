from functools import partial

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QCursor
from PySide2.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QMenu, QVBoxLayout
)

from hexrd.ui.constants import ViewType
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.markers import igor_marker
from hexrd.ui.tree_views.base_dict_tree_item_model import (
    BaseTreeItemModel, BaseDictTreeItemModel, BaseDictTreeView
)
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.tree_views.value_column_delegate import ValueColumnDelegate

# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
X_COL = KEY_COL + 1
Y_COL = X_COL + 1


class GenericPicksTreeItemModel(BaseDictTreeItemModel):

    def __init__(self, dictionary, coords_type=ViewType.polar, parent=None):
        super().__init__(dictionary, parent)

        self.root_item = TreeItem([''] * 3)
        self.coords_type = coords_type

        self.rebuild_tree()

    @property
    def coords_type(self):
        return self._coords_type

    @coords_type.setter
    def coords_type(self, v):
        self._coords_type = v
        self.update_root_item()

    def update_root_item(self):
        options = {
            ViewType.raw: ['i', 'j'],
            ViewType.cartesian: ['x', 'y'],
            ViewType.polar: ['2θ', 'η'],
        }

        if self.coords_type not in options:
            raise NotImplementedError(self.coords_type)

        labels = options[self.coords_type]
        row = self.root_item.row()
        for i in range(2):
            col = i + 1
            self.root_item.set_data(col, labels[i])
            index = self.createIndex(row, col, self.root_item)
            self.dataChanged.emit(index, index)

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        def is_coords(x):
            return (
                isinstance(x, (tuple, list)) and
                len(x) == 2 and
                all(isinstance(y, (int, float)) for y in x)
            )

        if is_coords(cur_config):
            x, y = cur_config
            cur_tree_item.set_data(X_COL, x)
            cur_tree_item.set_data(Y_COL, y)
            return
        elif isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, (list, tuple)):
            keys = range(len(cur_config))
        else:
            # This shouldn't happen
            raise Exception(f'Unknown item: {cur_config}')

        for key in keys:
            path = self.path_to_value(cur_tree_item, 0) + [key]
            if path in self.blacklisted_paths or str(key).startswith('_'):
                continue

            data = [key if isinstance(key, (str, int)) else '', None, None]
            tree_item = self.add_tree_item(data, cur_tree_item)
            self.recursive_add_tree_items(cur_config[key], tree_item)

    def path_to_value(self, tree_item, column):
        return self.path_to_item(tree_item) + [column - 1]


class GenericPicksTreeView(BaseDictTreeView):

    dict_modified = Signal()

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None, model_class=GenericPicksTreeItemModel,
                 model_class_kwargs=None):
        super().__init__(parent)

        self.canvas = canvas
        self.allow_hand_picking = True
        self.all_picks_line = None
        self.selected_picks_line = None
        self.is_deleting_picks = False
        self._show_all_picks = False

        if model_class_kwargs is None:
            model_class_kwargs = {}

        self.setModel(model_class(dictionary, coords_type, self,
                                  **model_class_kwargs))

        value_cols = [X_COL, Y_COL]
        all_cols = [KEY_COL] + value_cols
        for col in value_cols:
            self.setItemDelegateForColumn(col, ValueColumnDelegate(self))

        for col in all_cols:
            self.resizeColumnToContents(col)
            self.header().resizeSection(col, 200)

        # Allow extended selection
        self.set_extended_selection_mode()
        self.expand_rows()

        self.setup_lines()
        self.setup_connections()

    def setup_connections(self):
        self.selection_changed.connect(self.selection_was_changed)
        self.model().dict_modified.connect(self.data_was_modified)

    def selection_was_changed(self):
        if self.is_deleting_picks:
            # Don't re-highlight and re-draw for every pick that is deleted
            return

        self.highlight_selected_lines()
        self.draw_picks()

    def highlight_selected_lines(self):
        # Do nothing by default
        pass

    def data_was_modified(self):
        self.draw_picks()
        self.dict_modified.emit()

    def delete_selected_picks(self):
        self.is_deleting_picks = True
        try:
            self._delete_selected_picks()
        finally:
            self.is_deleting_picks = False

        self.selection_was_changed()

    def _delete_selected_picks(self):
        model = self.model()
        items_to_remove = []
        for item in self.selected_items:
            # These rows will actually be removed
            items_to_remove.append(item)

        if items_to_remove:
            model.remove_items(items_to_remove)
            self.draw_picks()

    @property
    def show_all_picks(self):
        return self._show_all_picks

    @show_all_picks.setter
    def show_all_picks(self, b):
        if self.show_all_picks == b:
            return

        self._show_all_picks = b
        self.update_line_colors()
        self.draw_picks()

    def set_show_all_picks(self, b):
        self.show_all_picks = b

    def draw_picks(self):
        self.clear_artists()
        if not self.canvas:
            return

        self.draw_all_picks()
        self.draw_selected_picks()

    @property
    def all_pick_items(self):
        # Recurse through all items and pull out all pick items
        # We assume an item is a pick item if it is not the root, and
        # it doesn't contain any None values.
        items = []

        def recurse(parent):
            for child in parent.child_items:
                if not any(x is None for x in child.data_list):
                    items.append(child)

                recurse(child)

        recurse(self.model().root_item)
        return items

    def draw_all_picks(self):
        if not self.show_all_picks:
            return

        xys = [item.data_list[1:] for item in self.all_pick_items]
        self.all_picks_line.set_data(list(zip(*xys)))
        self.canvas.draw_idle()

    def draw_selected_picks(self):
        if not self.selected_items:
            return

        xys = [item.data_list[1:] for item in self.selected_items]
        self.selected_picks_line.set_data(list(zip(*xys)))
        self.canvas.draw_idle()

    def clear_artists(self):
        if self.all_picks_line:
            self.all_picks_line.set_data([], [])

        if self.selected_picks_line:
            self.selected_picks_line.set_data([], [])

        self.canvas.draw_idle()

    def setup_lines(self):
        if not self.canvas:
            return

        plot_kwargs = {
            'color': 'b',
            'marker': igor_marker,
            'markeredgecolor': 'black',
            'markersize': 16,
            'linestyle': 'None',
        }

        if not self.all_picks_line:
            # empty line
            self.all_picks_line, = self.canvas.axis.plot([], [], **plot_kwargs)

        if not self.selected_picks_line:
            # empty line
            self.selected_picks_line, = self.canvas.axis.plot([], [],
                                                              **plot_kwargs)

        self.update_line_colors()

    def update_line_colors(self):
        selected_picks_line_color = 'b'
        if self.show_all_picks:
            # Make the selected lines bright green instead
            selected_picks_line_color = '#00ff13'

        self.selected_picks_line.set_color(selected_picks_line_color)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.delete_selected_picks()
        return super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        actions = {}

        index = self.indexAt(event.pos())
        model = self.model()
        item = model.get_item(index)
        path = model.path_to_item(item)
        line_name_clicked = len(path) == 1
        point_clicked = len(path) == 2
        line_name = str(path[0])
        selected_items = self.selected_items
        num_selected = len(selected_items)
        is_hand_pickable = self.is_hand_pickable

        menu = QMenu(self)

        # Helper functions
        def add_actions(d: dict):
            actions.update({menu.addAction(k): v for k, v in d.items()})

        def add_separator():
            if not actions:
                return
            menu.addSeparator()

        # Context menu methods
        def insert_item():
            if line_name_clicked:
                position = 0
                parent_item = item
            elif point_clicked:
                position = path[-1]
                parent_item = item.parent_item
            else:
                raise NotImplementedError

            new_item = TreeItem([position, 0., 0.])
            model.insert_items([new_item], parent_item, position)

            # Select the new item
            index = model.createIndex(new_item.row(), 0, new_item)
            self.setCurrentIndex(index)

            if is_hand_pickable:
                # Go ahead and get the user to hand pick the point...
                self.hand_pick_point(new_item, line_name)

        def hand_pick_item():
            self.hand_pick_point(item, line_name)

        # Action logic
        add_actions({'Insert': insert_item})

        if is_hand_pickable and point_clicked:
            add_actions({'Hand pick': hand_pick_item})

        if num_selected > 0:
            add_actions({'Delete': self.delete_selected_picks})

        if not actions:
            # No context menu
            return

        # Open up the context menu
        action_chosen = menu.exec_(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return

        # Run the function for the action that was chosen
        actions[action_chosen]()

    @property
    def has_canvas(self):
        return self.canvas is not None

    @property
    def is_hand_pickable(self):
        return self.allow_hand_picking and self.has_canvas

    def hand_pick_point(self, item, pick_label=''):
        kwargs = {
            'canvas': self.canvas,
            'parent': self,
            'single_pick_mode': True,
        }

        picker = LinePickerDialog(**kwargs)
        picker.current_pick_label = pick_label
        picker.ui.setWindowTitle(pick_label)
        picker.start()

        finished_func = partial(self.point_picked, item=item)
        picker.point_picked.connect(finished_func)

    def point_picked(self, x, y, item):
        model = self.model()
        left = model.createIndex(item.row(), 1, item)
        right = model.createIndex(item.row(), 2, item)

        model.setData(left, x)
        model.setData(right, y)

        # Flag it as changed
        model.dataChanged.emit(left, right)

    @property
    def coords_type(self):
        return self.model().coords_type

    @coords_type.setter
    def coords_type(self, v):
        self.model().coords_type = v


class GenericPicksTreeViewDialog(QDialog):

    dict_modified = Signal()

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None):
        super().__init__(parent)

        self.setWindowTitle('Edit Picks')

        self.setLayout(QVBoxLayout(self))

        self.tree_view = GenericPicksTreeView(dictionary, coords_type, canvas,
                                              self)
        self.layout().addWidget(self.tree_view)

        # Add a checkbox for showing all
        cb = QCheckBox('Show all picks', self)
        cb.setChecked(self.tree_view.show_all_picks)
        cb.toggled.connect(self.tree_view.set_show_all_picks)
        self.layout().addWidget(cb)

        # Add a button box for accept/cancel
        buttons = QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        self.button_box = QDialogButtonBox(buttons, self)
        self.layout().addWidget(self.button_box)

        self.resize(500, 500)

        self.setup_connections()

    def setup_connections(self):
        self.tree_view.dict_modified.connect(self.dict_modified.emit)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.finished.connect(self.on_finished)

    def on_finished(self):
        self.tree_view.clear_artists()
