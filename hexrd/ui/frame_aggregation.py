import copy

from hexrd import imageseries

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class FrameAggregation:

    def __init__(self, parent=None):
        self.parent = parent
        self.image_tab_widget = self.parent.parent().image_tab_widget
        self.ui = UiLoader().load_file('frame_aggregation.ui', parent)
        self.ims = {}
        self.results = {}

        self.setup_connections()

    def setup_connections(self):
        self.ui.view_stats.toggled.connect(self.toggle_editing)
        self.ui.function.currentIndexChanged.connect(self.select_fn)
        self.ui.apply_agg.clicked.connect(self.apply_stat)

    def toggle_editing(self):
        self.status = self.ui.view_stats.isChecked()
        self.ui.function.setEnabled(self.status)
        self.ui.label.setEnabled(self.status)
        self.ui.apply_agg.setEnabled(self.status)

        self.update_display()

    def select_fn(self, idx):
        self.fn = idx
        self.ui.percentage.setEnabled(idx == 4)

    def apply_stat(self):
        imgs = list(self.ims.keys())
        nframes = len(self.ims[imgs[0]])
        percent = self.ui.percentage.value()
        for key in self.ims.keys():
            ims = self.ims[key]
            if self.fn == 1:
                self.results[key] = imageseries.stats.average(ims, nframes)
            elif self.fn == 2:
                self.results[key] = imageseries.stats.max(ims, nframes)
            elif self.fn == 3:
                self.results[key] = imageseries.stats.median(ims, nframes)
            elif self.fn == 4:
                self.results[key] = imageseries.stats.percentile(
                    ims, percent, nframes)
            else:
                return

        HexrdConfig().images_dict = self.results
        self.parent.parent().image_tab_widget.load_images()

    def update_display(self):
        if self.status:
            self.show_agg_img()
        else:
            self.show_ims()

    def show_ims(self):
        HexrdConfig().imageseries_dict = self.ims
        self.parent.parent().image_tab_widget.load_images()

    def show_agg_img(self):
        self.ims = copy.deepcopy(HexrdConfig().imageseries())
        HexrdConfig().imageseries_dict = {}
        if self.results:
            HexrdConfig().images_dict = self.results
            self.parent.parent().image_tab_widget.load_images()
