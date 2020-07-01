from hexrd.cli.find_orientations import write_results
from hexrd.findorientations import find_orientations

from hexrd.ui.ui_loader import UiLoader

from hexrd.ui.indexing.tree_view import IndexingTreeView
from hexrd.ui.indexing.create_config import create_indexing_config


class IndexingDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('indexing_dialog.ui', parent)

        self.tree_view = IndexingTreeView(self.ui)
        self.ui.horizontal_layout.addWidget(self.tree_view)

        self.setup_connections()

    def setup_connections(self):
        self.ui.button_box.accepted.connect(self.run_indexing)

    def exec_(self):
        self.ui.exec_()

    def run_indexing(self):
        config = create_indexing_config()
        res = find_orientations(config)
        print('Finished! result is:', res)

        # For now, write out the data (won't do this in the future)
        write_results(res, config)
