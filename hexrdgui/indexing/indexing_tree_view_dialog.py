import yaml

from hexrdgui.hexrd_config import HexrdConfig
from hexrdgui.resource_loader import load_resource
from hexrdgui.tree_views.dict_tree_view import DictTreeViewDialog
from hexrdgui.utils import lazy_property

import hexrdgui.resources.indexing as indexing_resources


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

        self.expand_rows()

    @lazy_property
    def seed_search_defaults(self):
        file_name = 'seed_search_method_defaults.yml'
        text = load_resource(indexing_resources, file_name)
        return yaml.full_load(text)
