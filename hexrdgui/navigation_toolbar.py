from matplotlib import rc_context
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

from hexrdgui.utils import wrap_with_callbacks


class NavigationToolbar(NavigationToolbar2QT):

    default_button_blacklist = ['Subplots', 'Customize']

    def __init__(self, canvas, parent, coordinates=True,
                 button_blacklist=None, tight_savefig=True):
        # This adds the option to blacklist some of the buttons for the
        # toolbar. Options are currently: Home, Back, Forward, Pan, Zoom,
        # Subplots, Save.
        # Blacklisting the None object removes separators.
        # tight_savefig causes the figure to use the "tight" bbox when it is
        # saved.
        if button_blacklist is None:
            button_blacklist = self.default_button_blacklist
        elif not isinstance(button_blacklist, (list, tuple)):
            button_blacklist = [button_blacklist]

        old_toolitems = NavigationToolbar2QT.toolitems
        NavigationToolbar2QT.toolitems = [
            x for x in NavigationToolbar2QT.toolitems
            if x[0] not in button_blacklist
        ]

        super().__init__(canvas, parent, coordinates)

        # Restore the global navigation tool items for other parts of
        # the program to use them.
        NavigationToolbar2QT.toolitems = old_toolitems

        self.tight_savefig = tight_savefig

    @wrap_with_callbacks
    def home(self, *args):
        super().home(*args)

    @wrap_with_callbacks
    def back(self, *args):
        super().back(*args)

    @wrap_with_callbacks
    def forward(self, *args):
        super().back(*args)

    def save_figure(self, *args, **kwargs):
        context = {}
        if self.tight_savefig:
            context['savefig.bbox'] = 'tight'

        with rc_context(context):
            return super().save_figure(*args, **kwargs)
