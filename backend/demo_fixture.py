"""CLI-only fresh demo order; never resets or overwrites an existing business record."""

import argparse
from datetime import timedelta
from uuid import uuid4
from backend.db import session_scope
from backend.models import Order, now


def create_order(status="delivered", age=5):
    order_id = "demo_" + uuid4().hex[:16]
    with session_scope() as s:
        s.add(
            Order(
                id=order_id,
                customer_id="cus_ava",
                product_id="prod_speaker",
                quantity=1,
                amount_cents=12900,
                status=status,
                purchased_at=now() - timedelta(days=age + 3),
                delivered_at=now() - timedelta(days=age) if status == "delivered" else None,
            )
        )
    return order_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", choices=["delivered", "pending", "paid", "shipped"], default="delivered")
    parser.add_argument("--age", type=int, default=5)
    args = parser.parse_args()
    print(create_order(args.status, args.age))
