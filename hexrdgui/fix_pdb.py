import pdb
import sys


class FixedPdb(pdb.Pdb):
    """
    Since we re-direct stdout and stderr in other parts of the
    application, pdb can't interpret things like arrow keys
    and auto-complete correctly.
    This class fixes the issue by getting pdb to always use
    the default stdout and stderr.
    """

    def set_trace(self, *args, **kwargs):
        self._use_default_stdout_stderr()
        return super().set_trace(*args, **kwargs)

    def do_continue(self, *args, **kwargs):
        self._restore_stdout_stderr()
        return super().do_continue(*args, **kwargs)

    def _use_default_stdout_stderr(self):
        self._prev_stdout = sys.stdout
        self._prev_stderr = sys.stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def _restore_stdout_stderr(self):
        sys.stdout = self._prev_stdout
        sys.stderr = self._prev_stderr


def fix_pdb():
    if not isinstance(pdb.Pdb, FixedPdb):
        pdb.Pdb = FixedPdb
