import argparse
from pathlib import Path
from typing import Any


def check_positive_int(value: str) -> int:
    """Ensure the value is a positive int"""
    error_msg = f"invalid positive int value: {value}"

    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(error_msg)

    if ivalue <= 0:
        raise argparse.ArgumentTypeError(error_msg)

    return ivalue


def check_state_file(value: str) -> str:
    """Ensure the value is a valid state file"""
    path = Path(value)
    if not path.exists():
        raise argparse.ArgumentTypeError(f'No such file: "{value}"')

    return value


class ArgumentParser(argparse.ArgumentParser):
    """The ArgumentParser used by HEXRDGUI

    This class defines the arguments used by HEXRDGUI on the command line.
    It is created and stored in the HexrdConfig() object, so that it is
    accessible throughout the program.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:

        # Add hexrdgui-specific stuff here
        kwargs.update(
            dict(
                description='High energy x-ray diffraction data analysis',
            )
        )

        super().__init__(*args, **kwargs)

        # Add arguments here
        self.add_argument(
            'state_file',
            help='Load a state file or instrument config file during startup',
            type=check_state_file,
            nargs='?',
        )

        self.add_argument(
            '--ignore-settings',
            help='Ignore previous settings when HEXRDGUI starts',
            action='store_true',
        )

        self.add_argument(
            '-n',
            '--ncpus',
            help='Set the number of CPUs to use for parallel operations',
            type=check_positive_int,
        )
