from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from hexrd.material import Material

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.list_editor import ListEditor
from hexrdgui.ui_loader import UiLoader


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
        editor.item_added.connect(self.item_added)

        self.ui.import_from_cif.clicked.connect(self.import_from_cif)
        self.ui.import_from_defaults.clicked.connect(self.import_from_defaults)
        self.ui.export_to_cif.clicked.connect(self.export_to_cif)

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

    def item_added(self, new_name):
        material = Material()
        material.name = new_name
        HexrdConfig().add_material(new_name, material)

    def export_to_cif(self):
        caption = 'Select directory to export CIF files to'
        selected_dir = QFileDialog.getExistingDirectory(
            self.ui, caption, dir=HexrdConfig().working_dir)
        if not selected_dir:
            return

        HexrdConfig().working_dir = selected_dir
        # Export selected materials or all materials if none selected
        selections = self.editor.selected_items
        if not selections:
            selections = HexrdConfig().materials.values()
        for selected in self.editor.selected_items:
            material = HexrdConfig().material(selected)
            HexrdConfig().save_material_cif(material, selected_dir)

    def import_from_cif(self):
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            self.ui, 'Import Material', HexrdConfig().working_dir,
            'CIF files (*.cif)')

        if not selected_file:
            return

        HexrdConfig().working_dir = str(Path(selected_file).parent)
        new_name = HexrdConfig().import_material(selected_file)
        HexrdConfig().active_material = new_name

        self.update_editor_items()

    def import_from_defaults(self):
        label = 'Import Default Material'
        items = HexrdConfig().available_default_materials
        selected, accepted = QInputDialog.getItem(self.ui, 'HEXRD', label,
                                                  items, 0, False)
        if not accepted:
            return

        if selected in HexrdConfig().materials:
            # This material will be over-written. Confirm with the user.
            text = (
                f'Warning: "{selected}" already exists and will be '
                'overwritten. Proceed?'
            )
            response = QMessageBox.question(self.ui, 'Already Exists', text)
            if response == QMessageBox.No:
                return

        HexrdConfig().load_default_material(selected)


if __name__ == '__main__':
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = MaterialListEditor()

    dialog.ui.finished.connect(app.quit)
    dialog.ui.show()
    app.exec()
