from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT


class NavigationToolbar(NavigationToolbar2QT):

    def __init__(self, canvas, parent, coordinates=True):
        # Remove these buttons from the navigation toolbar
        nav_toolbar_blacklist = [
            'Subplots'
        ]
        old_toolitems = NavigationToolbar2QT.toolitems
        NavigationToolbar2QT.toolitems = [
            x for x in NavigationToolbar2QT.toolitems
            if x[0] not in nav_toolbar_blacklist
        ]

        super().__init__(canvas, parent, coordinates)

        # Restore the global navigation tool items for other parts of
        # the program to use them.
        NavigationToolbar2QT.toolitems = old_toolitems
