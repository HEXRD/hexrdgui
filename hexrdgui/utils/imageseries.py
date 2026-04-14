from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hexrd.core.imageseries.imageseriesabc import ImageSeriesABC


def get_monolithic_ims(
    subpanel_ims: ImageSeriesABC,
) -> ImageSeriesABC:
    """Get monolithic image from a subpanel's image series.

    Recursively unwraps the image series chain, collecting all
    non-rectangle operations and frame_list selections along the way.
    The result is a single image series rooted at the base adapter
    with all non-rectangle processing preserved.

    The chain may contain arbitrary nesting of:
    - ``ImageSeries`` / ``OmegaImageSeries`` (use ``_adapter``)
    - ``ProcessedImageSeries`` (use ``_imser``, hold ``_oplist``)
    """
    from hexrd.core.imageseries.process import ProcessedImageSeries

    # Walk the full chain, collecting non-rectangle ops and frame_lists.
    non_rect_ops: list = []
    frame_list: list[int] | None = None
    ims: ImageSeriesABC = subpanel_ims

    while True:
        if isinstance(ims, ProcessedImageSeries):
            # Collect ops (excluding rectangle) and frame_list
            non_rect_ops.extend(op for op in ims._oplist if op[0] != 'rectangle')
            if frame_list is None and ims._hasframelist:
                frame_list = list(ims._frames)
            ims = ims._imser
        elif hasattr(ims, '_adapter'):
            ims = ims._adapter
        else:
            # Reached the base adapter — stop.
            break

    # ims is now the root image series (e.g. FrameCacheImageSeriesAdapter
    # wrapped in ImageSeries).  Rebuild with only the collected ops.
    if not non_rect_ops and frame_list is None:
        return ims

    kwargs: dict = {}
    if frame_list is not None:
        kwargs['frame_list'] = frame_list

    return ProcessedImageSeries(ims, non_rect_ops, **kwargs)
