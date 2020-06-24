from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.indexing.indexing_tree_view import IndexingTreeView
from hexrd.ui.ui_loader import UiLoader


class IndexingDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('indexing_dialog.ui', parent)

        self.tree_view = IndexingTreeView(self.ui)
        self.ui.horizontal_layout.addWidget(self.tree_view)

        self.setup_connections()

    def setup_connections(self):
        pass

    def exec_(self):
        self.ui.exec_()
