"""Immutable contracts passed between agents.

Workers never share mutable state. Every response is a frozen handoff consumed by
the coordinator or by the next worker in the directed pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class LLMReview:
    model_name: str
    response_json: str
    agreed_with_guardrail: bool
    duration_ms: float


@dataclass(frozen=True)
class CaseRequest:
    case_id: str
    opened_at: str
    language: str
    message: str
    order_id: str
    policy_version: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CaseRequest":
        customer_request = value["customer_request"]
        return cls(
            case_id=value["case_id"],
            opened_at=value["opened_at"],
            language=customer_request["language"],
            message=customer_request["message"],
            order_id=customer_request["claimed_order_id"],
            policy_version=value["policy_version"],
        )


@dataclass(frozen=True)
class ItemFact:
    order_item_id: str
    product_id: str
    seller_id: str
    shipping_limit_date: datetime | None
    price: Decimal
    freight_value: Decimal


@dataclass(frozen=True)
class OrderSellerHandoff:
    order_id: str
    order_status: str
    delivered_carrier_date: datetime | None
    delivered_customer_date: datetime | None
    estimated_delivery_date: datetime | None
    items: tuple[ItemFact, ...]
    seller_ids: tuple[str, ...]
    late_seller_ids: tuple[str, ...]
    item_total: Decimal
    freight_total: Decimal
    llm_review: LLMReview


@dataclass(frozen=True)
class PaymentFact:
    payment_sequential: str
    payment_type: str
    payment_installments: int
    payment_value: Decimal


@dataclass(frozen=True)
class PaymentHandoff:
    order_id: str
    payments: tuple[PaymentFact, ...]
    payment_total: Decimal
    expected_order_total: Decimal
    difference: Decimal
    is_reconciled: bool
    is_split_payment: bool
    llm_review: LLMReview


@dataclass(frozen=True)
class DeliveryHandoff:
    order_id: str
    delivered_customer_date: datetime | None
    estimated_delivery_date: datetime | None
    is_late: bool
    is_within_estimate: bool
    late_seller_ids: tuple[str, ...]
    llm_review: LLMReview


@dataclass(frozen=True)
class ResponsibleParty:
    party_type: str
    party_id: str


@dataclass(frozen=True)
class PolicyDecision:
    primary_issue: str
    case_status: str
    confidence: float
    cause_code: str
    responsible_parties: tuple[ResponsibleParty, ...]
    recommended_refund: Decimal
    action: str
    llm_review: LLMReview


@dataclass(frozen=True)
class VerificationHandoff:
    accepted: bool
    errors: tuple[str, ...]
    llm_review: LLMReview

