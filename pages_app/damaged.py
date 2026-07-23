from lib.queue_view import render_queue


def render():
    render_queue(
        statuses=["damaged"],
        title="Damaged Queue",
        key_prefix="damagedq",
        metric_labels={"damaged": "Damaged"},
    )
