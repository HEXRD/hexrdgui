import argparse


def check_positive_int(value):
    """Ensure the value is a positive int"""
    error_msg = f"invalid positive int value: {value}"

    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(error_msg)

    if ivalue <= 0:
        raise argparse.ArgumentTypeError(error_msg)

    return ivalue


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

        self.add_argument(
            '-n', '--ncpus',
            type=check_positive_int,
            help='Set the number of CPUs to use for parallel operations',
        )
