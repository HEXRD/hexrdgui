from matplotlib.artist import Artist


def remove_artist(artist: Artist) -> None:
    # Starting in matplotlib 3.10, we cannot remove artists from a figure
    # that has already been cleared. I don't know of any easy way to check
    # if the axis has been cleared, though, so for now, we just try to
    # remove the artist and ignore the relevant exception if it occurs.
    try:
        artist.remove()
    except NotImplementedError:
        pass
