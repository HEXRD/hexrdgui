from pathlib import Path

from PySide2.QtWidgets import QFileDialog

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.list_editor import ListEditor
from hexrd.ui.ui_loader import UiLoader


class MaterialListEditor:
    """A list editor for materials"""

    def __init__(self, parent=None):
        self.ui = UiLoader().load_file('material_list_editor.ui', parent)

        self.editor = ListEditor(self.materials_names, parent)
        self.ui.list_editor_layout.addWidget(self.editor.ui)
        self.update_editor_items()

        self.setup_connections()

    def setup_connections(self):
        editor = self.editor

        editor.items_rearranged.connect(self.items_rearranged)
        editor.items_deleted.connect(self.items_deleted)
        editor.items_copied.connect(self.items_copied)
        editor.item_renamed.connect(self.item_renamed)

        self.ui.import_material.clicked.connect(self.import_material)

        HexrdConfig().materials_dict_modified.connect(self.update_editor_items)

    def update_editor_items(self):
        self.editor.items = self.materials_names

    @property
    def items(self):
        return self.editor.items

    @property
    def materials(self):
        return HexrdConfig().materials

    @property
    def materials_names(self):
        return list(self.materials)

    def items_rearranged(self):
        HexrdConfig().rearrange_materials(self.items)

    def items_deleted(self, deleted):
        HexrdConfig().remove_materials(deleted)

    def items_copied(self, old_names, new_names):
        HexrdConfig().copy_materials(old_names, new_names)

    def item_renamed(self, old_name, new_name):
        HexrdConfig().rename_material(old_name, new_name)

    def import_material(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Import Material', HexrdConfig().working_dir,
            'CIF files (*.cif)')

        if not selected_file:
            return

        HexrdConfig().working_dir = str(Path(selected_file).parent)
        new_name = HexrdConfig().import_material(selected_file)
        HexrdConfig().active_material = new_name

        self.update_editor_items()


if __name__ == '__main__':
    import sys

    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = MaterialListEditor()

    dialog.ui.finished.connect(app.quit)
    dialog.ui.show()
    app.exec_()
