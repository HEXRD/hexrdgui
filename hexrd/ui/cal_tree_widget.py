from PySide2.QtCore import Qt
from PySide2.QtWidgets import QMessageBox, QTreeWidget, QTreeWidgetItem


class CalTreeWidget(QTreeWidget):

    def __init__(self, cfg, parent=None):
        super(CalTreeWidget, self).__init__(parent)

        self.cfg = cfg
        self.rebuild_tree()
        self.setup_connections()

    def setup_connections(self):
        self.itemChanged.connect(self.item_changed)

    def rebuild_tree(self):
        block_signals = self.blockSignals(True)

        try:
            self.clear()

            self.setColumnCount(2)
            self.setHeaderLabels(['key', 'value'])
            self.header().resizeSection(0, 200)
            self.header().resizeSection(1, 200)

            for key in self.cfg.config.keys():
                tree_item = self.add_tree_item(key, None, self)
                tree_item.setExpanded(True)
                self.recursive_add_tree_items(self.cfg.config[key], tree_item)
        finally:
            self.blockSignals(block_signals)

    def add_tree_item(self, key, value, parent):
        tree_item = QTreeWidgetItem(parent)

        tree_item.setText(0, str(key))

        if value is not None:
            tree_item.setText(1, str(value))

        return tree_item

    def recursive_add_tree_items(self, cur_config, cur_tree_item):
        cur_text = cur_tree_item.text(0)
        if isinstance(cur_config, dict):
            keys = cur_config.keys()
        elif isinstance(cur_config, list):
            keys = range(len(cur_config))
        else:
            # This must be a value. Set it.
            cur_tree_item.setText(1, str(cur_config))
            cur_tree_item.setFlags(cur_tree_item.flags() | Qt.ItemIsEditable)
            return

        for key in keys:
            tree_item = self.add_tree_item(key, None, cur_tree_item)

            # Expand all except for the detectors
            if cur_tree_item.text(0) != 'detectors':
                tree_item.setExpanded(True)

            self.recursive_add_tree_items(cur_config[key], tree_item)

    def get_path_from_root(self, tree_item):
        path = []
        cur_tree_item = tree_item
        while True:
            text = cur_tree_item.text(0)
            if self._is_int(text):
                text = int(text)

            path.insert(0, text)
            cur_tree_item = cur_tree_item.parent()
            if cur_tree_item is None:
                break

        return path

    def item_changed(self, tree_item, column):
        path = self.get_path_from_root(tree_item)
        old_value = self.cfg.get_config_val(path)
        new_value = tree_item.text(column)

        # Convert the new value to the old value's type
        try:
            new_value = type(old_value)(new_value)
        except ValueError:
            msg = ('Could not convert ' + str(new_value) + ' to type ' +
                   str(type(old_value).__name__))
            QMessageBox.warning(self, 'HEXRD', msg)
            return

        self.cfg.set_config_val(path, new_value)

    def _is_int(self, s):
        try:
            int(s)
            return True
        except ValueError:
            return False
