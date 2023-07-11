from PySide2.QtWidgets import QFileDialog, QPushButton

import yaml

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.resource_loader import load_resource
from hexrd.ui.tree_views.dict_tree_view import DictTreeViewDialog
from hexrd.ui.utils import lazy_property

import hexrd.ui.resources.indexing as indexing_resources


class IndexingTreeViewDialog(DictTreeViewDialog):
    def __init__(self, parent=None):
        config = HexrdConfig().indexing_config['find_orientations']
        super().__init__(config, parent)
        self.setWindowTitle('Indexing Config')

        # Allow options to be selected for the key here
        combo_keys = {
            ('seed_search', 'method'): self.seed_search_defaults,
        }
        self.tree_view.combo_keys = combo_keys

        # Don't allow the user to see/modify the omega period.
        # This is deprecated, and we only set it programmatically where
        # needed.
        self.tree_view.blacklisted_paths = [('omega', 'period')]

        save_button = QPushButton('Save')
        save_button.clicked.connect(self.on_save_indexing_config_clicked)
        self.layout().addWidget(save_button)

        self.expand_rows()

    @lazy_property
    def seed_search_defaults(self):
        file_name = 'seed_search_method_defaults.yml'
        text = load_resource(indexing_resources, file_name)
        return yaml.full_load(text)

    def on_save_indexing_config_clicked(self):
        selected_file, _ = QFileDialog.getSaveFileName(
            self, 'Save Indexing Config', HexrdConfig().working_dir,
            'YAML files (*.yaml *.yml)')

        if not selected_file:
            return

        self.write_config(selected_file)

    def write_config(self, file):
        config = self.tree_view.model().config
        with open(file, 'w') as rf:
            yaml.dump({'find_orientations': config}, rf)
