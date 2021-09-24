from functools import partial

import numpy as np

from PySide2.QtCore import Qt
from PySide2.QtGui import QCursor
from PySide2.QtWidgets import QMenu

from hexrd.ui.constants import ViewType
from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.line_picker_dialog import LinePickerDialog
from hexrd.ui.overlays import overlay_from_name, path_to_hkl
from hexrd.ui.tree_views.base_dict_tree_item_model import (
    BaseTreeItemModel, BaseDictTreeItemModel, BaseDictTreeView
)
from hexrd.ui.tree_views.tree_item import TreeItem
from hexrd.ui.tree_views.value_column_delegate import ValueColumnDelegate
from hexrd.ui.utils import hkl_str_to_array


# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
X_COL = KEY_COL + 1
Y_COL = X_COL + 1


class PicksTreeItemModel(BaseDictTreeItemModel):

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


class PicksTreeView(BaseDictTreeView):

    def __init__(self, dictionary, coords_type=ViewType.polar, canvas=None,
                 parent=None):
        super().__init__(parent)

        self.canvas = canvas
        self.allow_hand_picking = True
        self.line = None
        self.is_deleting_picks = False

        self.setModel(PicksTreeItemModel(dictionary, coords_type, self))

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

    def setup_connections(self):
        self.selection_changed.connect(self.selection_was_changed)
        self.model().dict_modified.connect(self.data_was_modified)

    def selection_was_changed(self):
        if self.is_deleting_picks:
            # Don't re-highlight and re-draw for every pick that is deleted
            return

        self.highlight_selected_hkls()
        self.draw_selected_picks()

    def data_was_modified(self):
        self.draw_selected_picks()

    def clear_highlights(self):
        for overlay in HexrdConfig().overlays:
            overlay.setdefault('highlights', []).clear()

    def highlight_selected_hkls(self):
        self.clear_highlights()

        model = self.model()
        for item in self.selected_items:
            path = model.path_to_value(item, 0)
            # Example: ['diamond powder', 'IMAGE-PLATE-2', '1 1 1', 1, -1]
            overlay_name, detector_name, hkl_str, *others = path
            overlay = overlay_from_name(overlay_name)
            hkl = hkl_str_to_array(hkl_str)
            hkl_path = path_to_hkl(overlay, detector_name, hkl)
            overlay['highlights'].append(hkl_path)

        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

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
            path = model.path_to_item(item)
            if len(path) == 3:
                # It is a laue point. Just set it to nans.
                left = model.createIndex(item.row(), 1, item)
                right = model.createIndex(item.row(), 2, item)
                model.setData(left, np.nan)
                model.setData(right, np.nan)

                # Flag it as changed
                model.dataChanged.emit(left, right)
                continue
            elif len(path) != 4:
                raise NotImplementedError(path)

            # These rows will actually be removed
            items_to_remove.append(item)

        if items_to_remove:
            model.remove_items(items_to_remove)
            self.draw_selected_picks()

    def draw_selected_picks(self):
        if not self.canvas or not self.selected_items:
            self.clear_artists()
            return

        if not self.line:
            self.setup_line()

        xys = [item.data_list[1:] for item in self.selected_items]
        self.line.set_data(list(zip(*xys)))
        self.canvas.draw_idle()

    def clear_artists(self):
        if not self.line:
            return

        self.line.set_data([], [])
        self.canvas.draw_idle()

    def setup_line(self):
        if not self.canvas or self.line:
            return

        kwargs = {
            'color': 'b',
            'marker': '.',
            'linestyle': 'None',
        }

        # empty line
        self.line, = self.canvas.axis.plot([], [], **kwargs)

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
        powder_clicked = 'powder' in path[0]
        hkl_clicked = len(path) == 3
        powder_pick_clicked = len(path) == 4
        hkl_str = path[2] if hkl_clicked or powder_pick_clicked else ''
        laue_pick_clicked = hkl_clicked and not powder_clicked
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
            if hkl_clicked:
                position = 0
                parent_item = item
            elif powder_pick_clicked:
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
                self.hand_pick_point(new_item, hkl_str)

        def hand_pick_item():
            self.hand_pick_point(item, hkl_str)

        # Action logic
        if powder_clicked and (hkl_clicked or powder_pick_clicked):
            add_actions({'Insert': insert_item})

        if is_hand_pickable and (powder_pick_clicked or laue_pick_clicked):
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

    def hand_pick_point(self, item, hkl_str=''):
        kwargs = {
            'canvas': self.canvas,
            'parent': self,
            'single_pick_mode': True,
        }

        picker = LinePickerDialog(**kwargs)
        picker.current_hkl_label = f'Current hkl:  {hkl_str}'

        title = f'Pick point for:  {hkl_str}'
        picker.ui.setWindowTitle(title)
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
