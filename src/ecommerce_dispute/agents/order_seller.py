"""Order & Seller Agent: owns order/item/seller-domain investigation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ..contracts import ItemFact, OrderSellerHandoff
from ..llm import ModelGateway, review
from ..repository import OlistRepository


def parse_timestamp(value: str) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OrderSellerAgent:
    name = "order_seller_agent"

    def __init__(self, repository: OlistRepository, llm: ModelGateway) -> None:
        self._repository = repository
        self._llm = llm

    def investigate(self, order_id: str) -> OrderSellerHandoff:
        order = self._repository.order(order_id)
        carrier_date = parse_timestamp(order["order_delivered_carrier_date"])
        item_facts = tuple(
            ItemFact(
                order_item_id=row["order_item_id"],
                product_id=row["product_id"],
                seller_id=row["seller_id"],
                shipping_limit_date=parse_timestamp(row["shipping_limit_date"]),
                price=Decimal(row["price"]),
                freight_value=Decimal(row["freight_value"]),
            )
            for row in sorted(
                self._repository.items(order_id), key=lambda item: int(item["order_item_id"])
            )
        )
        seller_ids = tuple(dict.fromkeys(item.seller_id for item in item_facts))
        late_seller_ids = tuple(
            dict.fromkeys(
                item.seller_id
                for item in item_facts
                if carrier_date is not None
                and item.shipping_limit_date is not None
                and carrier_date > item.shipping_limit_date
            )
        )
        model_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Inspect order status, item ownership, and whether carrier handoff "
                "occurred after each item's shipping limit."
            ),
            payload={
                "order_status": order["order_status"],
                "item_count": len(item_facts),
                "seller_count": len(seller_ids),
                "carrier_handoff_after_any_shipping_limit": bool(late_seller_ids),
                "late_seller_count": len(late_seller_ids),
            },
            schema={
                "type": "object",
                "properties": {
                    "late_seller_count": {"type": "integer"},
                    "finding": {"type": "string"},
                },
                "required": ["late_seller_count", "finding"],
            },
        )
        return OrderSellerHandoff(
            order_id=order_id,
            order_status=order["order_status"],
            delivered_carrier_date=carrier_date,
            delivered_customer_date=parse_timestamp(order["order_delivered_customer_date"]),
            estimated_delivery_date=parse_timestamp(order["order_estimated_delivery_date"]),
            items=item_facts,
            seller_ids=seller_ids,
            late_seller_ids=late_seller_ids,
            item_total=sum((item.price for item in item_facts), Decimal("0")),
            freight_total=sum((item.freight_value for item in item_facts), Decimal("0")),
            llm_review=review(
                model_call,
                {"late_seller_count": len(late_seller_ids)},
                self._llm.model_name,
            ),
        )
