from hexrd.crystallography import hklToStr

from hexrd.ui.hexrd_config import HexrdConfig
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

    def __init__(self, dictionary, parent=None):
        super().__init__(dictionary, parent)

        # Don't allow editing for now. But we will add it soon in the future.
        self.editable = False

        self.root_item = TreeItem(['', '2θ', 'η'])
        self.rebuild_tree()

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

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)

        self.setModel(PicksTreeItemModel(dictionary, parent=self))

        value_cols = [X_COL, Y_COL]
        all_cols = [KEY_COL] + value_cols
        for col in value_cols:
            self.setItemDelegateForColumn(col, ValueColumnDelegate(self))

        for col in all_cols:
            self.resizeColumnToContents(col)
            self.header().resizeSection(col, 200)

        self.expand_rows()

        self.setup_connections()

    def setup_connections(self):
        self.selection_changed.connect(self.selection_was_changed)

    def selection_was_changed(self):
        self.highlight_selected_items()

    def clear_highlights(self):
        for overlay in HexrdConfig().overlays:
            overlay.setdefault('highlights', []).clear()

    def highlight_selected_items(self):
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

    def contextMenuEvent(self, event):
        # We will soon override this behavior. But for now, do nothing.
        return


def picks_to_tree_format(all_picks):
    def listify(sequence):
        sequence = list(sequence)
        for i, item in enumerate(sequence):
            if isinstance(item, tuple):
                sequence[i] = listify(item)

        return sequence

    tree_format = {}
    for entry in all_picks:
        hkl_picks = {}

        for det in entry['hkls']:
            hkl_picks[det] = {}
            for hkl, picks in zip(entry['hkls'][det], entry['picks'][det]):
                hkl_picks[det][hklToStr(hkl)] = listify(picks)

        name = f"{entry['material']} {entry['type']}"
        tree_format[name] = hkl_picks

    return tree_format


def tree_format_to_picks(tree_format):
    all_picks = []
    for name, entry in tree_format.items():
        material, type = name.split()
        hkls = {}
        picks = {}
        for det, hkl_picks in entry.items():
            hkls[det] = []
            picks[det] = []
            for hkl, picks in hkl_picks.items():
                hkls[det].append(list(map(int, hkl.split(','))))
                picks[det].append(picks)

        current = {
            'material': material,
            'type': type,
            'hkls': hkls,
            'picks': picks,
        }
        all_picks.append(current)

    return all_picks
