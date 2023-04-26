from PySide2.QtCore import QObject, Qt

from matplotlib import cm

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class EditColormapListDialog(QObject):

    def __init__(self, parent, cmap_editor):
        super().__init__(parent)
        loader = UiLoader()
        self.ui = loader.load_file('edit_colormaps_dialog.ui', parent)
        flags = self.ui.windowFlags()
        self.ui.setWindowFlags(flags | Qt.Tool)

        self.user_colormaps = HexrdConfig().limited_cmaps_list
        self.default = HexrdConfig().default_cmap
        self.cmap_editor = cmap_editor

        self.setup_connections()
        self.setup_gui()

    def show(self):
        self.ui.show()

    def setup_connections(self):
        self.ui.add.clicked.connect(self.add_cmap)
        self.ui.remove.clicked.connect(self.remove_cmap)
        self.ui.unused_colormaps.clicked.connect(self.cmap_selected)
        self.ui.user_colormaps.clicked.connect(self.default_cmap_selected)
        self.ui.make_default.clicked.connect(self.set_new_default)
        self.ui.button_box.accepted.connect(self.finalize)

    def setup_gui(self):
        all_cmaps = sorted(i[:-2] for i in dir(cm) if i.endswith('_r'))
        self.ui.unused_colormaps.addItems(all_cmaps)
        if not (defaults := HexrdConfig().limited_cmaps_list):
            defaults = [self.ui.unused_colormaps.findItems(
                HexrdConfig().default_cmap, Qt.MatchExactly)[0].text()]
        self.ui.user_colormaps.addItems(defaults)

    def add_cmap(self):
        selected_rows = self.ui.unused_colormaps.selectedIndexes()
        selected = [i.text() for i in self.ui.unused_colormaps.selectedItems()]
        self.ui.user_colormaps.addItems(selected)
        for item in selected_rows:
            self.ui.unused_colormaps.takeItem(item.row())

    def remove_cmap(self):
        selected_rows = self.ui.user_colormaps.selectedIndexes()
        selected = [i.text() for i in self.ui.user_colormaps.selectedItems()]
        self.ui.unused_colormaps.addItems(selected)
        for idx, item in enumerate(selected_rows):
            if selected[idx] == self.default:
                continue
            self.ui.user_colormaps.takeItem(item.row())
        self.ui.remove.setEnabled(False)

    def update_button_statuses(self):
        add_enabled = len(self.ui.unused_colormaps.selectedItems())
        user_cmaps = self.ui.user_colormaps.selectedItems()
        if (remove_enabled := len(user_cmaps)) == 1:
            remove_enabled = user_cmaps[0].text() != self.default
        default_enabled = len(user_cmaps) == 1
        self.ui.add.setEnabled(add_enabled)
        self.ui.remove.setEnabled(remove_enabled)
        self.ui.make_default.setEnabled(default_enabled)

    def cmap_selected(self):
        self.ui.user_colormaps.clearSelection()
        self.update_button_statuses()

    def default_cmap_selected(self):
        self.ui.unused_colormaps.clearSelection()
        self.update_button_statuses()

    def set_new_default(self):
        if selections := self.ui.user_colormaps.selectedItems():
            default = selections[0].text()
        self.default = default
        self.ui.default_colormap_text.setText(self.default)
        self.ui.user_colormaps.clearSelection()
        self.ui.unused_colormaps.clearSelection()
        self.update_button_statuses()

    def finalize(self):
        self.user_colormaps.clear()
        for i in range(self.ui.user_colormaps.count()):
            self.user_colormaps.append(self.ui.user_colormaps.item(i).text())
        HexrdConfig().limited_cmaps_list = self.user_colormaps
        HexrdConfig().default_cmap = self.default
        if HexrdConfig().show_all_colormaps:
            self.cmap_editor.load_all_cmaps()
        else:
            self.cmap_editor.load_cmaps()
