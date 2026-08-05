"""Policy Agent: applies EC_POLICY_V1 in the README's strict priority order."""

from __future__ import annotations

from decimal import Decimal

from ..config import POLICY_VERSION
from ..contracts import (
    CaseRequest,
    DeliveryHandoff,
    OrderSellerHandoff,
    PaymentHandoff,
    PolicyDecision,
    ResponsibleParty,
)
from ..llm import ModelGateway, review


class PolicyAgent:
    name = "policy_agent"

    def __init__(self, llm: ModelGateway) -> None:
        self._llm = llm

    def decide(
        self,
        case: CaseRequest,
        order: OrderSellerHandoff,
        payment: PaymentHandoff,
        delivery: DeliveryHandoff,
    ) -> PolicyDecision:
        if case.policy_version != POLICY_VERSION:
            raise ValueError(f"Unsupported policy version: {case.policy_version}")

        if order.order_status == "canceled" and payment.payment_total > 0:
            issue = "canceled_order_paid"
            cause = "ORDER_CANCELED_AFTER_PAYMENT"
            parties = (ResponsibleParty("platform", "OLIST_PLATFORM"),)
            refund = payment.payment_total
            action = "issue_full_refund"
        elif order.order_status == "unavailable" and payment.payment_total > 0:
            issue = "unavailable_order_paid"
            cause = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
            parties = (ResponsibleParty("platform", "OLIST_PLATFORM"),)
            refund = payment.payment_total
            action = "issue_full_refund"
        elif delivery.is_late and delivery.late_seller_ids:
            issue = "late_delivery_seller"
            cause = "SELLER_HANDOFF_AFTER_LIMIT"
            parties = tuple(
                ResponsibleParty("seller", seller_id)
                for seller_id in delivery.late_seller_ids[:3]
            )
            refund = order.freight_total
            action = "refund_freight"
        elif delivery.is_late and not delivery.late_seller_ids:
            issue = "late_delivery_logistics"
            cause = "CARRIER_DELIVERED_AFTER_ESTIMATE"
            parties = (ResponsibleParty("logistics_provider", "LOGISTICS_PROVIDER"),)
            refund = order.freight_total
            action = "refund_freight"
        elif payment.is_split_payment and payment.is_reconciled:
            issue = "valid_split_payment"
            cause = "MULTIPLE_PAYMENTS_RECONCILED"
            parties = ()
            refund = Decimal("0")
            action = "explain_valid_split_payment"
        elif delivery.is_within_estimate and payment.is_reconciled:
            issue = "unsupported_late_claim"
            cause = "DELIVERY_WITHIN_ESTIMATE"
            parties = ()
            refund = Decimal("0")
            action = "reject_late_refund"
        else:
            raise ValueError(f"Case {case.case_id} does not match EC_POLICY_V1")

        refund_basis = (
            "full_payment"
            if issue in {"canceled_order_paid", "unavailable_order_paid"}
            else "freight"
            if issue in {"late_delivery_seller", "late_delivery_logistics"}
            else "none"
        )

        model_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Apply EC_POLICY_V1 in strict priority: canceled paid; unavailable paid; "
                "late delivery with late seller handoff; late logistics; reconciled split "
                "payment; delivery within estimate with reconciled payment."
            ),
            payload={
                "order_status": order.order_status,
                "payment_positive": payment.payment_total > 0,
                "payment_reconciled": payment.is_reconciled,
                "split_payment": payment.is_split_payment,
                "delivery_late": delivery.is_late,
                "delivery_within_estimate": delivery.is_within_estimate,
                "late_seller_count": len(delivery.late_seller_ids),
            },
            schema={
                "type": "object",
                "properties": {
                    "primary_issue": {"type": "string"},
                    "cause_code": {"type": "string"},
                    "refund_basis": {"type": "string"},
                    "action": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "primary_issue",
                    "cause_code",
                    "refund_basis",
                    "action",
                    "rationale",
                ],
            },
        )
        return PolicyDecision(
            primary_issue=issue,
            case_status="action_required" if refund > 0 else "no_action",
            confidence=1.0,
            cause_code=cause,
            responsible_parties=parties,
            recommended_refund=refund,
            action=action,
            llm_review=review(
                model_call,
                {
                    "primary_issue": issue,
                    "cause_code": cause,
                    "refund_basis": refund_basis,
                    "action": action,
                },
                self._llm.model_name,
            ),
        )
