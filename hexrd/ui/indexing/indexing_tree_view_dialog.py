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
        self.dict_tree_view.combo_keys = combo_keys

    @lazy_property
    def seed_search_defaults(self):
        file_name = 'seed_search_method_defaults.yml'
        text = load_resource(indexing_resources, file_name)
        return yaml.full_load(text)
