import os

from PySide2.QtCore import Signal, Slot, QSettings
from PySide2.QtWidgets import QFileDialog, QTabWidget

from hexrd.ui.image_canvas import ImageCanvas

class ImageTabWidget(QTabWidget):

    # Emitted when new images are loaded
    new_images_loaded = Signal()

    def __init__(self, parent=None):
        super(ImageTabWidget, self).__init__(parent)
        self.image_canvases = [ImageCanvas(self)]
        self.image_files = []

        # These will get set later
        self.cmap = None
        self.norm = None

        self.set_tabbed_view(False)

    def allocate_canvases(self):
        while len(self.image_canvases) < len(self.image_files):
            self.image_canvases.append(ImageCanvas(self))

    def load_images_tabbed(self):
        self.clear()
        self.allocate_canvases()
        for i, file in enumerate(self.image_files):
            self.image_canvases[i].load_images(image_files=[file])
            self.addTab(self.image_canvases[i], os.path.basename(file))

        self.update_canvas_cmaps()
        self.update_canvas_norms()

    def load_images_untabbed(self):
        self.clear()
        self.image_canvases[0].load_images(image_files=self.image_files)
        self.addTab(self.image_canvases[0], '')

        self.update_canvas_cmaps()
        self.update_canvas_norms()

    def load_images(self, image_files):
        self.image_files = image_files

        if self.tabbed_view:
            self.load_images_tabbed()
        else:
            self.load_images_untabbed()

        self.new_images_loaded.emit()

    @Slot()
    def open_files(self):
        # Get the most recent images dir
        settings = QSettings()
        images_dir = settings.value('images_dir')

        selected_files, selected_filter = QFileDialog.getOpenFileNames(
            self, dir=images_dir)

        if selected_files:
            # Save the chosen dir
            settings.setValue('images_dir', selected_files[0])
            return self.load_images(selected_files)

    @Slot(bool)
    def set_tabbed_view(self, tabbed_view=False):
        self.tabbed_view = tabbed_view
        if self.tabbed_view:
            self.tabBar().show()
            self.load_images_tabbed()
        else:
            self.tabBar().hide()
            self.load_images_untabbed()

    def show_calibration(self, config):
        self.clear()
        self.image_canvases[0].show_calibration(config, self.image_files)
        self.addTab(self.image_canvases[0], '')

    def show_polar_calibration(self, config):
        self.clear()
        self.image_canvases[0].show_polar_calibration(config, self.image_files)
        self.addTab(self.image_canvases[0], '')

    def active_canvases(self):
        """Get the canvases that are actively being used"""
        if not self.tabbed_view:
            return [self.image_canvases[0]]

        return self.image_canvases[:len(self.image_files)]

    def value_range(self):
        """Get the range of values in the images"""
        mins_maxes = [x.get_min_max() for x in self.active_canvases()]
        minimum = min([x[0] for x in mins_maxes])
        maximum = max([x[1] for x in mins_maxes])

        return minimum, maximum

    def update_canvas_cmaps(self):
        if self.cmap is not None:
            for canvas in self.active_canvases():
                canvas.set_cmap(self.cmap)

    def update_canvas_norms(self):
        if self.norm is not None:
            for canvas in self.active_canvases():
                canvas.set_norm(self.norm)

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.update_canvas_cmaps()

    def set_norm(self, norm):
        self.norm = norm
        self.update_canvas_norms()

if __name__ == '__main__':
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # This will just test for __init__ errors
    ImageTabWidget()
