class MaskType:
    region = 'region'    # Rectangle or Ellipse mask
    polygon = 'polygon'  # Hand drawn mask
    threshold = 'threshold'
    powder = 'powder'
    laue = 'laue'
    pinhole = 'pinhole'

CURRENT_MASK_VERSION = 2


class MaskStatus:
    none = 0
    visible = 1
    boundary = 2
    all = 3
