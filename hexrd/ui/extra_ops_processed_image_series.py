from hexrd.imageseries.process import ProcessedImageSeries


class ExtraOpsProcessedImageSeries(ProcessedImageSeries):
    """This class is here to add extra ops that aren't in hexrd..."""

    SUBTRACT = 'subtract'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.addop(self.SUBTRACT, self._subtract)

    def _subtract(self, img, subtrahend):
        return img - subtrahend
