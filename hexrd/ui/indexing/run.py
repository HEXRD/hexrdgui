from hexrd.findorientations import generate_eta_ome_maps
from hexrd.xrdutil import EtaOmeMaps

from hexrd.ui.indexing.create_config import create_indexing_config
from hexrd.ui.indexing.ome_maps_select_dialog import OmeMapsSelectDialog
from hexrd.ui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog


class IndexingRunner:
    def __init__(self, parent=None):
        self.parent = parent
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None

        self.ome_maps = None

    def clear(self):
        self.ome_maps_select_dialog = None
        self.ome_maps_viewer_dialog = None

        self.ome_maps = None

    def run(self):
        # We will go through these steps:
        # 1. Have the user select/generate eta omega maps
        # 2. Have the user view and threshold the eta omega maps
        # 3. ...
        self.select_ome_maps()

    def select_ome_maps(self):
        dialog = OmeMapsSelectDialog(self.parent)
        dialog.accepted.connect(self.ome_maps_selected)
        dialog.rejected.connect(self.clear)
        dialog.show()
        self.ome_maps_select_dialog = dialog

    def ome_maps_selected(self):
        dialog = self.ome_maps_select_dialog
        if dialog is None:
            return

        if dialog.mode == 'load':
            self.ome_maps = EtaOmeMaps(dialog.file_name)
        else:
            # Create a full indexing config
            config = create_indexing_config()
            self.ome_maps = generate_eta_ome_maps(config, save=False)

        self.ome_maps_select_dialog = None
        self.view_ome_maps()

    def view_ome_maps(self):
        # Now, show the Ome Map viewer

        ### TEMPORARY SECTION ###
        import hexrd.ui.indexing.ome_maps_viewer_dialog
        import importlib

        importlib.reload(hexrd.ui.indexing.ome_maps_viewer_dialog)
        from hexrd.ui.indexing.ome_maps_viewer_dialog import OmeMapsViewerDialog
        ### END TEMPORARY SECTION ###

        dialog = OmeMapsViewerDialog(self.ome_maps, self.parent)
        dialog.accepted.connect(self.ome_maps_viewed)
        dialog.rejected.connect(self.clear)
        dialog.show()

        self.ome_maps_viewer_dialog = dialog

    def ome_maps_viewed(self):
        pass
