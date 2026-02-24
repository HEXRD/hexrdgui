import pdb
import sys
from typing import Any


class FixedPdb(pdb.Pdb):
    """
    Since we re-direct stdout and stderr in other parts of the
    application, pdb can't interpret things like arrow keys
    and auto-complete correctly.
    This class fixes the issue by getting pdb to always use
    the default stdout and stderr.
    """

    def set_trace(self, *args: Any, **kwargs: Any) -> None:
        self._use_default_stdout_stderr()
        return super().set_trace(*args, **kwargs)

    def do_continue(self, *args: Any, **kwargs: Any) -> Any:
        self._restore_stdout_stderr()
        return super().do_continue(*args, **kwargs)

    def _use_default_stdout_stderr(self) -> None:
        self._prev_stdout = sys.stdout
        self._prev_stderr = sys.stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def _restore_stdout_stderr(self) -> None:
        sys.stdout = self._prev_stdout
        sys.stderr = self._prev_stderr


def fix_pdb() -> None:
    if not isinstance(pdb.Pdb, FixedPdb):
        pdb.Pdb = FixedPdb  # type: ignore[misc]
