from typing import Any

from PySide6.QtWidgets import QFileDialog, QWidget

from hexrd.xrdutil import EtaOmeMaps

from hexrdgui.hexrd_config import HexrdConfig


def plot_grains(
    grains_table: Any,
    ome_maps: EtaOmeMaps | None = None,
    parent: QWidget | None = None,
) -> None:
    # Avoid a circular import
    from hexrdgui.indexing.indexing_results_dialog import IndexingResultsDialog

    if ome_maps is None:
        selected_file, selected_filter = QFileDialog.getOpenFileName(
            parent,
            'Load Eta Omega Maps',
            HexrdConfig().working_dir,
            'NPZ files (*.npz)',
        )

        if not selected_file:
            return

        ome_maps = EtaOmeMaps(selected_file)

    dialog = IndexingResultsDialog(ome_maps, grains_table, parent)
    dialog.plot_grains_mode = True
    dialog.exec()
