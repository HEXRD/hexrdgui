import argparse


class ArgumentParser(argparse.ArgumentParser):
    """The ArgumentParser used by HEXRDGUI

    This class defines the arguments used by HEXRDGUI on the command line.
    It is created and stored in the HexrdConfig() object, so that it is
    accessible throughout the program.
    """
    def __init__(self, *args, **kwargs):

        # Add hexrdgui-specific stuff here
        kwargs.update(dict(
            description='High energy x-ray diffraction data analysis',
        ))

        super().__init__(*args, **kwargs)

        # Add arguments here
        self.add_argument(
            '--ignore-settings',
            action='store_true',
            help='Ignore previous settings when HEXRDGUI starts',
        )
