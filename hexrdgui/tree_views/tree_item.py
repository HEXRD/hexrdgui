from __future__ import annotations

from typing import Any

import numpy as np


class TreeItem:
    # A simple TreeItem class to be used with QTreeView...

    def __init__(
        self,
        data_list: Any,
        parent_item: TreeItem | None = None,
    ) -> None:
        self.data_list = data_list
        self.parent_item = parent_item
        self.child_items: list[TreeItem] = []
        if self.parent_item:
            # Add itself automatically to its parent's children...
            self.parent_item.append_child(self)

    def append_child(self, child: TreeItem) -> None:
        self.child_items.append(child)

    def child(self, row: int) -> TreeItem | None:
        if row < 0 or row >= len(self.child_items):
            return None

        return self.child_items[row]

    def child_count(self) -> int:
        return len(self.child_items)

    def clear_children(self) -> None:
        self.child_items.clear()

    def column_count(self) -> int:
        return len(self.data_list)

    def data(self, column: int) -> Any:
        if column < 0 or column >= len(self.data_list):
            return None
        return self.data_list[column]

    def set_data(self, column: int, val: Any) -> None:
        if column < 0 or column >= len(self.data_list):
            return

        self.data_list[column] = self._preprocess_value(val)

    def _preprocess_value(self, val: Any) -> Any:
        # We must convert some values to native python types, or Qt
        # will not know how to display them.
        get_item = (isinstance(val, np.ndarray) and val.size == 1) or isinstance(
            val, np.generic
        )
        if get_item:
            # Convert to native python type
            val = val.item()

        return val

    def row(self) -> int:
        if self.parent_item:
            return self.parent_item.child_items.index(self)
        return 0
