from PIL import Image, ImageDraw
import numpy as np


def polygon_to_mask(coords, mask_shape):
    # This comes out very slightly different than scikit-image's polygon
    # method, with the only differences being along the edges (plus or minus
    # a pixel).
    img = Image.fromarray(np.ones(mask_shape, dtype=bool))
    ImageDraw.Draw(img).polygon(coords.flatten().tolist(), outline=0, fill=0)

    return np.array(img)
