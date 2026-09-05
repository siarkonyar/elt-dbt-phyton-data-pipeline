import queue #cant name the file queue because of this import


def drain(source_queue, max_rows):
    """Take up to max_rows trades off the queue without ever blocking."""
    items = []

    while len(items) < max_rows:
        try:
            items.append(source_queue.get_nowait())#gets an item from the que and puts it in the items list.
        except queue.Empty:#if the queue is empty break the loop
            break

    return tuple(items)