"""Payment Agent: reconciles payment rows against item plus freight totals."""

from __future__ import annotations

from decimal import Decimal

from ..config import PAYMENT_TOLERANCE_BRL
from ..contracts import OrderSellerHandoff, PaymentFact, PaymentHandoff
from ..llm import ModelGateway, review
from ..repository import OlistRepository


class PaymentAgent:
    name = "payment_agent"

    def __init__(self, repository: OlistRepository, llm: ModelGateway) -> None:
        self._repository = repository
        self._llm = llm

    def reconcile(self, order: OrderSellerHandoff) -> PaymentHandoff:
        payments = tuple(
            PaymentFact(
                payment_sequential=row["payment_sequential"],
                payment_type=row["payment_type"],
                payment_installments=int(row["payment_installments"]),
                payment_value=Decimal(row["payment_value"]),
            )
            for row in sorted(
                self._repository.payments(order.order_id),
                key=lambda payment: int(payment["payment_sequential"]),
            )
        )
        payment_total = sum((payment.payment_value for payment in payments), Decimal("0"))
        expected_total = order.item_total + order.freight_total
        difference = payment_total - expected_total
        is_reconciled = abs(difference) <= Decimal(PAYMENT_TOLERANCE_BRL)
        is_split_payment = len(payments) >= 2
        model_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Reconcile the sum of payment rows against item_total plus freight_total. "
                "A split payment has at least two rows; tolerance is 0.10 BRL."
            ),
            payload={
                "order_id": order.order_id,
                "item_total_brl": str(order.item_total),
                "freight_total_brl": str(order.freight_total),
                "payment_values_brl": [str(row.payment_value) for row in payments],
                "tolerance_brl": PAYMENT_TOLERANCE_BRL,
            },
            schema={
                "type": "object",
                "properties": {
                    "is_reconciled": {"type": "boolean"},
                    "is_split_payment": {"type": "boolean"},
                    "finding": {"type": "string"},
                },
                "required": ["is_reconciled", "is_split_payment", "finding"],
            },
        )
        return PaymentHandoff(
            order_id=order.order_id,
            payments=payments,
            payment_total=payment_total,
            expected_order_total=expected_total,
            difference=difference,
            is_reconciled=is_reconciled,
            is_split_payment=is_split_payment,
            llm_review=review(
                model_call,
                {
                    "is_reconciled": is_reconciled,
                    "is_split_payment": is_split_payment,
                },
                self._llm.model_name,
            ),
        )
