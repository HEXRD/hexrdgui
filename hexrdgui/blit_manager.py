from collections.abc import Generator, Sequence, ValuesView
from typing import Any

from matplotlib.artist import Artist

from hexrdgui.utils.matplotlib import remove_artist


class BlitManager:
    def __init__(self, canvas: Any) -> None:
        """
        Parameters
        ----------
        canvas : FigureCanvasAgg
            The canvas to work with. The background will be cached when needed.

        This class was modified from here:
        https://matplotlib.org/stable/users/explain/animations/blitting.html
        """
        self.canvas = canvas
        self.bg = None

        # This dict can contain nested dicts, lists, etc.
        # But all non-container values must be artists.
        # We will find them recursively.
        self.artists: dict[str, Any] = {}

        # grab the background on every draw
        self.cid = canvas.mpl_connect("draw_event", self.on_draw)

    def disconnect(self) -> None:
        self.remove_artists()

        if self.cid is not None:
            self.canvas.mpl_disconnect(self.cid)
            self.cid = None

    def on_draw(self, event: Any) -> None:
        """Callback to register with 'draw_event'."""
        cv = self.canvas
        if event is not None:
            if event.canvas != cv:
                msg = (
                    f'Event canvas "{event.canvas}" does not match the '
                    f'manager canvas "{cv}"'
                )
                raise RuntimeError(msg)

        if not cv.figure.axes:
            # Ignore the request, as there are currently no axes
            return

        self.bg = cv.copy_from_bbox(cv.figure.bbox)
        self.draw_all_artists()

    def remove_artists(self, *path: Any) -> None:
        # The *path is an arbitrary path into the artist dict
        parent = None
        d = self.artists
        for key in path:
            if key not in d:
                # It already doesn't exist. Just return.
                return

            parent = d
            d = d[key]

        for artist in _recursive_yield_artists(d):
            remove_artist(artist)

        if parent:
            del parent[key]
        else:
            self.artists.clear()

    def draw_all_artists(self) -> None:
        """Draw all of the animated artists."""
        fig = self.canvas.figure
        for artist in _recursive_yield_artists(self.artists):
            fig.draw_artist(artist)

    def update(self) -> None:
        """Update the screen with animated artists."""
        cv = self.canvas
        fig = cv.figure

        # paranoia in case we missed the draw event,
        if self.bg is None:
            self.on_draw(None)
        else:
            # restore the background
            cv.restore_region(self.bg)
            # draw all of the animated artists
            self.draw_all_artists()
            # update the GUI state
            cv.blit(fig.bbox)

        # let the GUI event loop process anything it has to do
        cv.flush_events()


def _recursive_yield_artists(artists: Any) -> Generator[Artist, None, None]:
    if isinstance(artists, dict):
        yield from _recursive_yield_artists(artists.values())
    elif isinstance(artists, (Sequence, ValuesView)):
        for v in artists:
            if isinstance(v, Artist):
                yield v
            else:
                yield from _recursive_yield_artists(v)
