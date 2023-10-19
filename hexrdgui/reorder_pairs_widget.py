import copy

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSizePolicy, QWidget

from hexrdgui.ui_loader import UiLoader


class ReorderPairsWidget(QObject):

    items_reordered = Signal()

    def __init__(self, items, titles, parent=None):
        # The items should be a list of tuples of length two, like
        # (first, second).
        super().__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('reorder_pairs_widget.ui', parent)

        self.combo_boxes = []

        self.titles = titles
        self.parent = parent
        self.items = items

    @property
    def items(self):
        return self._items

    @items.setter
    def items(self, v):
        self._items = copy.deepcopy(v)
        self.update_table()
        self.ui.table.resizeColumnsToContents()

    @property
    def titles(self):
        table = self.ui.table
        num_cols = table.columnCount()
        return [table.horizontalHeaderItem(i) for i in range(num_cols)]

    @titles.setter
    def titles(self, v):
        self.ui.table.setHorizontalHeaderLabels(v)

    def create_table_widget(self, w):
        # These are required to center the widget...
        tw = QWidget(self.ui.table)
        layout = QHBoxLayout(tw)
        layout.addWidget(w)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return tw

    def create_combo_box(self, i, j):
        value = self.items[i][j]
        options = [x[j] for x in self.items]

        cb = QComboBox(self.ui.table)
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cb.setSizePolicy(size_policy)
        cb.addItems(options)
        cb.setCurrentIndex(options.index(value))

        def callback():
            self.item_edited(i, j, cb.currentText())

        cb.currentIndexChanged.connect(callback)
        self.combo_boxes.append(cb)
        return self.create_table_widget(cb)

    def clear_table(self):
        self.combo_boxes.clear()
        self.ui.table.clearContents()

    def update_table(self):
        self.clear_table()
        self.ui.table.setRowCount(len(self.items))
        for i, pair in enumerate(self.items):
            for j in range(len(pair)):
                w = self.create_combo_box(i, j)
                self.ui.table.setCellWidget(i, j, w)

    def item_edited(self, i, j, new_value):
        # Find the old index of the new value and do a swap
        old_index = [x[j] for x in self.items].index(new_value)

        old_row = list(self.items[old_index])
        new_row = list(self.items[i])

        # Swap the j between them
        old_row[j], new_row[j] = new_row[j], old_row[j]

        self.items[old_index] = tuple(old_row)
        self.items[i] = tuple(new_row)

        self.update_table()
        self.items_reordered.emit()


if __name__ == '__main__':
    # Make an example to test out
    from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout

    app = QApplication()

    titles = ['Items', 'Indices']

    items = [
        ('Item1', '1'),
        ('Item2', '2'),
        ('Item3', '3'),
        ('Item4', '4'),
    ]

    dialog = QDialog()
    layout = QVBoxLayout()
    dialog.setLayout(layout)
    widget = ReorderPairsWidget(items, titles)
    layout.addWidget(widget.ui)

    def items_reordered():
        print(f'Items reordered: {widget.items}')

    widget.items_reordered.connect(items_reordered)
    dialog.exec()
