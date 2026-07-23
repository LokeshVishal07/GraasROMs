from lib.queue_view import render_queue


def render():
    render_queue(
        statuses=["refund_only"],
        title="Refund Only",
        key_prefix="refundonlyq",
        metric_labels={"refund_only": "Refund Only"},
        empty_hint="Warehouse marks an order Refund Only when the buyer was refunded without the "
                    "item needing to come back for inspection.",
    )
