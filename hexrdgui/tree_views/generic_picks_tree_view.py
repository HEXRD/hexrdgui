from functools import partial
from itertools import cycle

import matplotlib.pyplot as plt

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QMenu, QVBoxLayout
)

from hexrdgui.constants import ViewType
from hexrdgui.line_picker_dialog import LinePickerDialog
from hexrdgui.markers import igor_marker
from hexrdgui.tree_views.base_dict_tree_item_model import (
    BaseTreeItemModel, BaseDictTreeItemModel, BaseDictTreeView
)
from hexrdgui.tree_views.tree_item import TreeItem
from hexrdgui.tree_views.value_column_delegate import ValueColumnDelegate

# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
X_COL = KEY_COL + 1
Y_COL = X_COL + 1


class GenericPicksTreeItemModel(BaseDictTreeItemModel):

    def __init__(self, dictionary, coords_type=ViewType.polar, parent=None):
        super().__init__(dictionary, parent)

        self.root_item = TreeItem([''] * 3)
        self.coords_type = coords_type

        """
        A zero-layer nested structure looks like this:
        {
            'line1': [(0, 0), (1, 1)],
            'line2': [(2, 2), (3, 4)],
        }

        A one-layer nested structure looks like this:
        {
            'XRS1': {
                'line1': [(0, 0), (1, 1)],
                'line2': [(2, 2), (3, 4)],
            },
            'XRS2': {
                'line1': [(5, 6), (7, 8)],
                'line2': [(9, 9), (10, 10)],
            },
        }

        By default, we assume one-layer nested structure.
        """
        self.num_layers_nested = 1

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

    dict_modified = Signal(QModelIndex)

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None, model_class=GenericPicksTreeItemModel,
                 model_class_kwargs=None):
        super().__init__(parent)

        self.canvas = canvas
        self.allow_hand_picking = True
        self.all_picks_line_artists = []
        self.selected_picks_line_artists = []
        self.is_deleting_picks = False
        self._show_all_picks = True
        self.new_line_name_generator = None
        self._current_picker = None
        self.skip_pick_item_list = []

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

        self.setup_connections()

        self.draw_picks()

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

    def data_was_modified(self, index):
        self.draw_picks()
        self.dict_modified.emit(index)

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
    def num_layers_nested(self) -> int:
        return self.model().num_layers_nested

    @property
    def show_all_picks(self):
        return self._show_all_picks

    @show_all_picks.setter
    def show_all_picks(self, b):
        if self.show_all_picks == b:
            return

        self._show_all_picks = b
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
        # Take self.all_pick_items_grouped and flatten them out
        items = []
        for group in self.all_pick_items_grouped.values():
            items.extend(group)
        return items

    @property
    def all_pick_items_grouped(self):
        # Recurse through all items and pull out all pick items
        # We assume an item is a pick item if it is not the root, and
        # it doesn't contain any None values.
        # These items will be grouped by parent.
        items = {}

        def recurse(parent):
            group = []
            for child in parent.child_items:
                if child in self.skip_pick_item_list:
                    continue

                if not any(x is None for x in child.data_list):
                    group.append(child)

                recurse(child)

            if group:
                items[parent] = group

        recurse(self.model().root_item)
        return items

    @property
    def selected_items_grouped(self):
        selected_items = self.selected_items
        if not selected_items:
            # Return early
            return {}

        # Use all the same keys as all_pick_items_grouped so that the colors
        # from the cycler match up.
        selected_grouped = {key: [] for key in self.all_pick_items_grouped}
        for item in selected_items:
            selected_grouped[item.parent_item].append(item)

        return selected_grouped

    @property
    def default_artist_settings(self):
        return {
            'line': {
                'marker': igor_marker,
                'markeredgecolor': 'black',
                'markersize': 16,
                'linestyle': 'None',
            },
            'spot': {
                'marker': 'o',
                'fillstyle': 'none',
                'markersize': 8,
                'markeredgewidth': 2,
                'linewidth': 0,
            },
        }

    @property
    def highlighted_artist_settings(self):
        return {
            'line': {
                'marker': igor_marker,
                'markeredgecolor': 'yellow',
                'markersize': 16,
                'linestyle': 'None',
            },
            'spot': {
                'marker': 'o',
                'fillstyle': 'none',
                'markersize': 8,
                'markeredgewidth': 2,
                'linewidth': 0,
            },
        }

    def create_color_cycler(self):
        prop_cycle = plt.rcParams['axes.prop_cycle']
        return cycle(prop_cycle.by_key()['color'])

    def item_type(self, tree_item):
        # Assume 'line' always for generic calibration.
        # Subclasses can add logic to change type to 'spot' as well.
        return 'line'

    def draw_all_picks(self):
        if not self.show_all_picks:
            return

        artist_settings = self.default_artist_settings
        color_cycler = self.create_color_cycler()

        for group in self.all_pick_items_grouped.values():
            # Always cycle the color
            color = next(color_cycler)

            if not group:
                continue

            # Get the type of the first item, and use that for settings
            item_type = self.item_type(group[0])
            settings = artist_settings[item_type]
            settings['color'] = color

            xys = [item.data_list[1:] for item in group]
            artist, = self.canvas.axis.plot(*list(zip(*xys)), **settings)
            self.all_picks_line_artists.append(artist)

        self.canvas.draw_idle()

    def draw_selected_picks(self):
        if not self.selected_items:
            return

        artist_settings = self.default_artist_settings
        if self.show_all_picks:
            # Use highlighted artist settings instead
            artist_settings = self.highlighted_artist_settings

        color_cycler = self.create_color_cycler()

        for group in self.selected_items_grouped.values():
            # Always cycle to the next color, even if the group is empty,
            # so that the colors will match up with all_pick_items_grouped
            color = next(color_cycler)

            if not group:
                continue

            # Get the type of the first item, and use that for settings
            item_type = self.item_type(group[0])
            settings = artist_settings[item_type]

            if self.show_all_picks and item_type == 'spot':
                # Force yellow for highlight
                settings['color'] = 'yellow'
            else:
                settings['color'] = color

            xys = [item.data_list[1:] for item in group]
            artist, = self.canvas.axis.plot(*list(zip(*xys)), **settings)
            self.selected_picks_line_artists.append(artist)

        self.canvas.draw_idle()

    def clear_artists(self):
        while self.all_picks_line_artists:
            self.all_picks_line_artists.pop(0).remove()

        while self.selected_picks_line_artists:
            self.selected_picks_line_artists.pop(0).remove()

        self.canvas.draw_idle()

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
        line_name_clicked = len(path) == self.num_layers_nested + 1
        point_clicked = len(path) == self.num_layers_nested + 2
        line_name = (
            str(path[self.num_layers_nested])
            if len(path) > self.num_layers_nested else 'None'
        )
        selected_items = self.selected_items
        num_selected = len(selected_items)
        is_hand_pickable = self.is_hand_pickable

        if self.model().is_disabled_path(path):
            # If it is a disabled path, do not create the context menu
            return

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

            pick_label = f'Inserting points into: {line_name}'
            return self._insert_picks(parent_item, position, pick_label)

        def hand_pick_item():
            self.hand_pick_point(item, line_name)

        # Action logic
        if line_name_clicked and self.can_add_lines:
            # The path to the new line will include all but the selected one
            append = partial(self.append_new_line, path[:-1])
            add_actions({'Append new line': append})

        add_actions({'Insert': insert_item})

        if is_hand_pickable and point_clicked:
            add_actions({'Hand pick': hand_pick_item})

        if num_selected > 0:
            add_actions({'Delete': self.delete_selected_picks})

        if not actions:
            # No context menu
            return

        # Open up the context menu
        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return

        # Run the function for the action that was chosen
        actions[action_chosen]()

    def _insert_picks(self, parent_item, position, pick_label):
        model = self.model()

        if not self.is_hand_pickable:
            new_item = TreeItem([position, 0., 0.])
            model.insert_items([new_item], parent_item, position)

            # Select the new item
            index = model.createIndex(new_item.row(), 0, new_item)
            self.setCurrentIndex(index)
            return

        kwargs = {
            'canvas': self.canvas,
            'parent': self,
        }

        picker = LinePickerDialog(**kwargs)
        picker.current_pick_label = pick_label
        picker.ui.setWindowTitle(pick_label)
        picker.ui.view_picks.setVisible(False)
        picker.start()

        def on_line_completed():
            # Just accept it
            picker.ui.accept()

        def on_accepted():
            nonlocal position
            original_position = position
            new_line = picker.line_data[0]
            new_items = []
            for x, y in new_line.tolist():
                new_items.append(TreeItem([position, x, y]))
                position += 1

            model.insert_items(new_items, parent_item, original_position)

            # Select the last new item
            last_item = new_items[-1]
            index = model.createIndex(last_item.row(), 0, last_item)
            self.setCurrentIndex(index)

        picker.accepted.connect(on_accepted)
        picker.line_completed.connect(on_line_completed)

        self._current_picker = picker

    @property
    def has_canvas(self):
        return self.canvas is not None

    @property
    def is_hand_pickable(self):
        return self.allow_hand_picking and self.has_canvas

    @property
    def can_add_lines(self):
        return self.new_line_name_generator and self.has_canvas

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

        self._current_picker = picker

    def point_picked(self, x, y, item):
        model = self.model()
        left = model.createIndex(item.row(), 1, item)
        right = model.createIndex(item.row(), 2, item)

        model.setData(left, x)
        model.setData(right, y)

        # Flag it as changed
        model.dataChanged.emit(left, right)

    def on_accepted(self):
        # Check if the line picker should be accepted
        picker = self._current_picker
        if (
            picker is not None and
            picker.ui.isVisible() and
            picker.line_data and
            picker.line_data[0].size != 0
        ):
            # Accept the line
            self._current_picker.ui.accept()

    def append_new_line(self, path):
        name = self.new_line_name_generator(path)
        config = self.model().config_path(path)

        if name in config:
            msg = f'name {name} already exists in config! {list(config)}'
            raise Exception(msg)

        pick_label = f'Picking points for: {name}'
        kwargs = {
            'canvas': self.canvas,
            'parent': self,
        }

        picker = LinePickerDialog(**kwargs)
        picker.current_pick_label = pick_label
        picker.ui.setWindowTitle(pick_label)
        picker.ui.view_picks.setVisible(False)
        picker.start()

        def on_line_completed():
            # Just accept it
            picker.ui.accept()

        accepted_func = partial(self.finished_appending_new_line,
                                path=path, name=name, picker=picker)
        picker.accepted.connect(accepted_func)
        picker.line_completed.connect(on_line_completed)

        self._current_picker = picker

    def finished_appending_new_line(self, path, name, picker):
        new_line = picker.line_data[0]
        config = self.model().config_path(path)

        config[name] = new_line.tolist()
        self.model().rebuild_tree()
        self.draw_picks()
        self.expand_rows()

    @property
    def coords_type(self):
        return self.model().coords_type

    @coords_type.setter
    def coords_type(self, v):
        self.model().coords_type = v


class GenericPicksTreeViewDialog(QDialog):

    dict_modified = Signal(QModelIndex)

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

        # Use accepted and rejected so this will be done before finished()
        self.accepted.connect(self.on_accepted)
        self.rejected.connect(self.on_rejected)

    def on_accepted(self):
        self.tree_view.on_accepted()
        self.on_finished()

    def on_rejected(self):
        self.on_finished()

    def on_finished(self):
        self.tree_view.clear_artists()
