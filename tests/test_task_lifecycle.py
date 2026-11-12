from threading import Event, Timer

from r2_companion.services.tasks import LocalTasks


def test_local_workers_finish_before_shutdown_and_never_deliver_stale_callbacks(qapp):
    tasks = LocalTasks()
    started, finish = Event(), Event()
    received = []
    def operation():
        started.set()
        finish.wait(5)
        return "finished"
    assert tasks.submit(operation, received.append)
    assert started.wait(2)
    timer = Timer(0.05, finish.set)
    timer.start()
    tasks.close()
    timer.join()
    qapp.processEvents()
    assert tasks.pool.activeThreadCount() == 0 and received == []
    assert not tasks.submit(lambda: None, received.append)
