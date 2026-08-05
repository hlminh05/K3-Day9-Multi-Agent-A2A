"""Delivery Agent: compares actual delivery with the committed date."""

from ..contracts import DeliveryHandoff, OrderSellerHandoff
from ..llm import ModelGateway, review


class DeliveryAgent:
    name = "delivery_agent"

    def __init__(self, llm: ModelGateway) -> None:
        self._llm = llm

    def assess(self, order: OrderSellerHandoff) -> DeliveryHandoff:
        has_dates = (
            order.delivered_customer_date is not None
            and order.estimated_delivery_date is not None
        )
        is_late = bool(
            has_dates and order.delivered_customer_date > order.estimated_delivery_date
        )
        is_within_estimate = bool(
            has_dates and order.delivered_customer_date <= order.estimated_delivery_date
        )
        model_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Compare actual customer delivery timestamp with the estimated timestamp. "
                "Equal timestamps are within estimate."
            ),
            payload={
                "both_dates_present": has_dates,
                "actual_after_estimate": is_late,
                "actual_within_estimate": is_within_estimate,
            },
            schema={
                "type": "object",
                "properties": {
                    "is_late": {"type": "boolean"},
                    "is_within_estimate": {"type": "boolean"},
                    "finding": {"type": "string"},
                },
                "required": ["is_late", "is_within_estimate", "finding"],
            },
        )
        return DeliveryHandoff(
            order_id=order.order_id,
            delivered_customer_date=order.delivered_customer_date,
            estimated_delivery_date=order.estimated_delivery_date,
            is_late=is_late,
            is_within_estimate=is_within_estimate,
            late_seller_ids=order.late_seller_ids,
            llm_review=review(
                model_call,
                {"is_late": is_late, "is_within_estimate": is_within_estimate},
                self._llm.model_name,
            ),
        )
