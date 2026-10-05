from hexrdgui.async_worker import AsyncWorker, check_cancelled


def test_cancelled_worker_stops_quietly(qtbot) -> None:
    # `qtbot` provides the QApplication for the worker's signals
    calls = []

    def fn() -> str:
        calls.append('started')
        worker.cancel()
        check_cancelled()
        calls.append('not reached')
        return 'result'

    worker = AsyncWorker(fn)
    emitted: list = []
    worker.signals.result.connect(lambda x: emitted.append(('result', x)))
    worker.signals.error.connect(lambda x: emitted.append(('error', x)))
    worker.signals.finished.connect(lambda: emitted.append(('finished',)))
    worker.run()

    assert calls == ['started']
    assert emitted == [('finished',)]

    # Outside of a worker, this does nothing
    check_cancelled()
