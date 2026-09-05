import queue

from buffer import drain


def make_queue(items):
    source = queue.Queue()
    for item in items:
        source.put(item)
    return source


def test_returns_empty_tuple_when_queue_is_empty():
    assert drain(queue.Queue(), 10) == ()


def test_returns_everything_when_there_are_fewer_items_than_max():
    assert drain(make_queue([1, 2, 3]), 10) == (1, 2, 3)


def test_preserves_fifo_order():
    assert drain(make_queue(["a", "b", "c"]), 10) == ("a", "b", "c")


def test_stops_at_max_rows_and_leaves_the_rest_on_the_queue():
    source = make_queue([1, 2, 3, 4, 5])

    taken = drain(source, 2)

    assert taken == (1, 2)
    assert source.qsize() == 3


def test_does_not_block_when_asked_for_more_than_the_queue_holds():
    # If drain used get() instead of get_nowait(), this hangs forever.
    assert drain(make_queue([1]), 100) == (1,)