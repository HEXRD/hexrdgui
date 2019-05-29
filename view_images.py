import sys

from PySide2.QtWidgets import QApplication

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas
)
from matplotlib.figure import Figure
import matplotlib.pyplot as plt


class Images(FigureCanvas):

    def __init__(self, parent=None, image_files=None):

        fig = Figure()
        super(Images, self).__init__(fig)

        cols = 2
        rows = len(image_files) // cols

        for i, file in enumerate(image_files):
            axis = fig.add_subplot(rows, cols, i + 1)
            img = plt.imread(file)
            axis.imshow(img)


if __name__ == '__main__':

    app = QApplication(sys.argv)

    image_files = ['0.tiff', '1.tiff', '2.tiff', '3.tiff']

    images = Images(image_files=image_files)
    images.show()

    # start event processing
    sys.exit(app.exec_())
