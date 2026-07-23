from lib.queue_view import render_queue


def render():
    render_queue(
        statuses=["not_received"],
        title="Return Not Received",
        key_prefix="notrecvq",
        metric_labels={"not_received": "Not Received"},
    )
