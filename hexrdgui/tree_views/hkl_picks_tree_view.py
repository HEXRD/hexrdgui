import numpy as np

from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.line_picker_dialog import LinePickerDialog
from hexrdgui.overlays import Overlay
from hexrdgui.tree_views.base_dict_tree_item_model import BaseTreeItemModel
from hexrdgui.tree_views.generic_picks_tree_view import (
    GenericPicksTreeView, TreeItem
)
from hexrdgui.utils import hkl_str_to_array

# Global constants
KEY_COL = BaseTreeItemModel.KEY_COL
X_COL = KEY_COL + 1
Y_COL = X_COL + 1


class HKLPicksTreeView(GenericPicksTreeView):

    def item_type(self, tree_item):
        root_item = self.model().root_item

        parents_to_root = 1
        parent = tree_item.parent_item
        while parent is not root_item:
            parent = parent.parent_item
            parents_to_root += 1

        if parents_to_root == 3:
            return 'spot'
        elif parents_to_root == 4:
            return 'line'

        raise Exception(f'Unknown parents_to_root: {parents_to_root}')

    def clear_highlights(self):
        for overlay in HexrdConfig().overlays:
            overlay.clear_highlights()

    def highlight_selected_lines(self):
        self.highlight_selected_hkls()

    def highlight_selected_hkls(self):
        self.clear_highlights()

        model = self.model()
        for item in self.selected_items:
            path = model.path_to_value(item, 0)
            # Example: ['diamond powder', 'IMAGE-PLATE-2', '1 1 1', 1, -1]
            overlay_name, detector_name, hkl_str, *others = path
            overlay = Overlay.from_name(overlay_name)
            hkl = hkl_str_to_array(hkl_str)
            overlay.highlight_hkl(detector_name, hkl)

        HexrdConfig().flag_overlay_updates_for_all_materials()
        HexrdConfig().overlay_config_changed.emit()

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
            self.draw_picks()

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

            pick_label = f'Inserting points into: {hkl_str}'
            return self._insert_picks(parent_item, position, pick_label)

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
        action_chosen = menu.exec(QCursor.pos())

        if action_chosen is None:
            # No action chosen
            return

        # Run the function for the action that was chosen
        actions[action_chosen]()
