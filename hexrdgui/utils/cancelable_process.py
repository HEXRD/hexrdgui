from concurrent.futures import ProcessPoolExecutor
from functools import partial
from psutil import Process
import time


class CancelableProcess:
    """A wrapper to start a cancelable process, and either retrieve
    the results, or cancel it.

    The class is initialized with a function: proc = CancelableProcess(func)

    The function is called with `results = proc.run()`, which forwards all
    args and kwargs to the function, and returns the results of the function.
    If the function needs to be canceled, call `proc.cancel()` from another
    thread. Then the running process will be killed, along with recursively
    all child processes. A ProcessCanceled exception will then be raised
    within `proc.run()`.

    The function and all arguments need to be pickle-able, since it is
    executed in a separate process. If pickling will cause a large
    performance hit, then it is advisable to look for another solution.
    """
    def __init__(self, func):
        self.func = func

        # This variable will most definitely be read/written by multiple
        # threads, so we must ensure it is thread-safe. We are currently
        # relying on the GIL for this thread-safety.
        self._canceled = False

    def run(self, *args, **kwargs):
        f = partial(self.func, *args, **kwargs)
        return run_cancelable_process(f, self._get_canceled)

    def _get_canceled(self):
        return self._canceled

    def cancel(self):
        self._canceled = True


class ProcessCanceled(Exception):
    pass


def run_cancelable_process(func, check_if_canceled_func):
    """func is a unary function to execute in a separate process. If it
    contains captured variables, they must all be pickle-able, as they will
    be pickled.

    check_if_canceled_func is a unary function that should return a boolean:
    True if canceled and False if not canceled. It will be called repeatedly,
    until it either returns True, or the process finishes.

    If the process is canceled, SIGKILL is sent to the process and to
    recursively all children of the process. Then, a ProcessCanceled exception
    is raised.
    """

    # ProcessPoolExecutor is used for convenience.
    # It is easier to retrieve Python object results this way.
    with ProcessPoolExecutor(max_workers=1) as executor:
        # Start the process
        future = executor.submit(func)

        # While it is running, constantly check if it was canceled.
        while not future.done():
            if check_if_canceled_func():
                # It was canceled
                for pid in executor._processes:
                    # Kill the process and recursively all children
                    process = Process(pid)
                    children = process.children(recursive=True)
                    for p in (process, *children):
                        p.kill()
                raise ProcessCanceled

            # Wait 1/4 second before trying again
            time.sleep(0.25)

        return future.result()


if __name__ == '__main__':

    def func():
        time.sleep(3)
        return 'Done!'

    cancel = True

    def check_if_canceled_func():
        # Cancel the first time it is called
        return cancel

    try:
        result = run_cancelable_process(
            func, check_if_canceled_func=check_if_canceled_func)
    except ProcessCanceled:
        print('Process was canceled')
    else:
        print('Process finished! Result was:', result)

    # It should succeed this time
    cancel = False
    result = run_cancelable_process(
        func, check_if_canceled_func=check_if_canceled_func)
    print('Second time succeeded. Result was:', result)
