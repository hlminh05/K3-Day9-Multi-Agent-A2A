"""Verifier Agent: independently checks schema, source IDs, money and policy."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..config import (
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE_IDS,
    MAX_RESPONSIBLE_PARTIES,
    MAX_ROOT_CAUSES,
    PAYMENT_TOLERANCE_BRL,
)
from ..contracts import CaseRequest, VerificationHandoff
from ..llm import ModelGateway, review
from ..repository import OlistRepository


ISSUE_RULES = {
    "canceled_order_paid": (
        "ORDER_CANCELED_AFTER_PAYMENT",
        "issue_full_refund",
        "platform",
        "OLIST_PLATFORM",
    ),
    "unavailable_order_paid": (
        "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "issue_full_refund",
        "platform",
        "OLIST_PLATFORM",
    ),
    "late_delivery_seller": (
        "SELLER_HANDOFF_AFTER_LIMIT",
        "refund_freight",
        "seller",
        None,
    ),
    "late_delivery_logistics": (
        "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "refund_freight",
        "logistics_provider",
        "LOGISTICS_PROVIDER",
    ),
    "valid_split_payment": (
        "MULTIPLE_PAYMENTS_RECONCILED",
        "explain_valid_split_payment",
        None,
        None,
    ),
    "unsupported_late_claim": (
        "DELIVERY_WITHIN_ESTIMATE",
        "reject_late_refund",
        None,
        None,
    ),
}


class VerifierAgent:
    name = "verifier_agent"

    def __init__(self, repository: OlistRepository, llm: ModelGateway) -> None:
        self._repository = repository
        self._llm = llm

    def verify(self, case: CaseRequest, output: dict[str, Any]) -> VerificationHandoff:
        errors: list[str] = []
        try:
            self._verify_shape(output, errors)
            self._verify_content(case, output, errors)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            errors.append(f"malformed_output:{exc}")
        accepted = not errors
        model_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Review the proposed dispute output for internal consistency. Check that "
                "refund/action/status align and evidence IDs have allowed prefixes."
            ),
            payload={
                "case_id": case.case_id,
                "assessment": output.get("assessment"),
                "root_cause_analysis": output.get("root_cause_analysis"),
                "evidence_ids": output.get("evidence_ids"),
                "financial_resolution": output.get("financial_resolution"),
                "resolution_actions": output.get("resolution_actions"),
            },
            schema={
                "type": "object",
                "properties": {
                    "accepted": {"type": "boolean"},
                    "audit_note": {"type": "string"},
                },
                "required": ["accepted", "audit_note"],
            },
        )
        return VerificationHandoff(
            accepted=accepted,
            errors=tuple(errors),
            llm_review=review(
                model_call, {"accepted": accepted}, self._llm.model_name
            ),
        )

    @staticmethod
    def _verify_shape(output: dict[str, Any], errors: list[str]) -> None:
        expected_top = {
            "case_id",
            "assessment",
            "affected_entities",
            "root_cause_analysis",
            "evidence_ids",
            "financial_resolution",
            "resolution_actions",
        }
        if set(output) != expected_top:
            errors.append("schema:top_level_keys")
        assessment = output["assessment"]
        if not 0 <= assessment["confidence"] <= 1:
            errors.append("schema:confidence_range")
        if assessment["case_status"] not in {"action_required", "no_action"}:
            errors.append("schema:case_status")
        entities = output["affected_entities"]
        for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            if len(entities[key]) > MAX_ENTITY_IDS:
                errors.append(f"limit:{key}")
        if len(output["evidence_ids"]) > MAX_EVIDENCE_IDS:
            errors.append("limit:evidence_ids")
        roots = output["root_cause_analysis"]
        if len(roots["ranked_causes"]) > MAX_ROOT_CAUSES:
            errors.append("limit:ranked_causes")
        if len(roots["responsible_parties"]) > MAX_RESPONSIBLE_PARTIES:
            errors.append("limit:responsible_parties")
        if len(output["resolution_actions"]) > MAX_ACTIONS:
            errors.append("limit:resolution_actions")

    def _verify_content(
        self, case: CaseRequest, output: dict[str, Any], errors: list[str]
    ) -> None:
        order = self._repository.order(case.order_id)
        items = sorted(
            self._repository.items(case.order_id), key=lambda row: int(row["order_item_id"])
        )
        payments = sorted(
            self._repository.payments(case.order_id),
            key=lambda row: int(row["payment_sequential"]),
        )
        item_total = sum((Decimal(row["price"]) for row in items), Decimal("0"))
        freight_total = sum(
            (Decimal(row["freight_value"]) for row in items), Decimal("0")
        )
        payment_total = sum(
            (Decimal(row["payment_value"]) for row in payments), Decimal("0")
        )
        issue, late_sellers = self._independent_issue(
            order, items, payments, item_total, freight_total, payment_total
        )
        cause, action, party_type, fixed_party_id = ISSUE_RULES[issue]

        if output["case_id"] != case.case_id:
            errors.append("case_id:mismatch")
        assessment = output["assessment"]
        if assessment["primary_issue"] != issue:
            errors.append("policy:primary_issue")
        expected_refund = (
            payment_total
            if issue in {"canceled_order_paid", "unavailable_order_paid"}
            else freight_total
            if issue in {"late_delivery_seller", "late_delivery_logistics"}
            else Decimal("0")
        )
        expected_status = "action_required" if expected_refund > 0 else "no_action"
        if assessment["case_status"] != expected_status:
            errors.append("policy:case_status")

        expected_entities = {
            "order_ids": [case.order_id],
            "item_ids": [
                f"{case.order_id}:{row['order_item_id']}" for row in items[:MAX_ENTITY_IDS]
            ],
            "seller_ids": list(
                dict.fromkeys(row["seller_id"] for row in items)
            )[:MAX_ENTITY_IDS],
            "payment_ids": [
                f"{case.order_id}:{row['payment_sequential']}"
                for row in payments[:MAX_ENTITY_IDS]
            ],
        }
        if output["affected_entities"] != expected_entities:
            errors.append("entities:mismatch")

        financial = output["financial_resolution"]
        expected_money = {
            "currency": "BRL",
            "item_total_brl": self._as_float(item_total),
            "freight_total_brl": self._as_float(freight_total),
            "payment_total_brl": self._as_float(payment_total),
            "recommended_refund_brl": self._as_float(expected_refund),
        }
        if financial != expected_money:
            errors.append("financial:mismatch")

        roots = output["root_cause_analysis"]
        if roots["ranked_causes"] != [{"cause_code": cause, "rank": 1}]:
            errors.append("policy:root_cause")
        if party_type is None:
            expected_parties: list[dict[str, str]] = []
        elif party_type == "seller":
            expected_parties = [
                {"party_type": "seller", "party_id": seller_id}
                for seller_id in late_sellers[:MAX_RESPONSIBLE_PARTIES]
            ]
        else:
            expected_parties = [
                {"party_type": party_type, "party_id": str(fixed_party_id)}
            ]
        if roots["responsible_parties"] != expected_parties:
            errors.append("policy:responsible_parties")
        if output["resolution_actions"] != [action]:
            errors.append("policy:resolution_actions")

        self._verify_evidence(
            case.order_id, items, payments, cause, output["evidence_ids"], errors
        )

    def _independent_issue(
        self,
        order: Any,
        items: list[Any],
        payments: list[Any],
        item_total: Decimal,
        freight_total: Decimal,
        payment_total: Decimal,
    ) -> tuple[str, list[str]]:
        def timestamp(value: str) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        carrier = timestamp(order["order_delivered_carrier_date"])
        delivered = timestamp(order["order_delivered_customer_date"])
        estimated = timestamp(order["order_estimated_delivery_date"])
        late_sellers = list(
            dict.fromkeys(
                row["seller_id"]
                for row in items
                if carrier is not None
                and timestamp(row["shipping_limit_date"]) is not None
                and carrier > timestamp(row["shipping_limit_date"])
            )
        )
        is_late = delivered is not None and estimated is not None and delivered > estimated
        is_within = (
            delivered is not None and estimated is not None and delivered <= estimated
        )
        reconciled = (
            abs(payment_total - item_total - freight_total)
            <= Decimal(PAYMENT_TOLERANCE_BRL)
        )
        if order["order_status"] == "canceled" and payment_total > 0:
            return "canceled_order_paid", late_sellers
        if order["order_status"] == "unavailable" and payment_total > 0:
            return "unavailable_order_paid", late_sellers
        if is_late and late_sellers:
            return "late_delivery_seller", late_sellers
        if is_late and not late_sellers:
            return "late_delivery_logistics", late_sellers
        if len(payments) >= 2 and reconciled:
            return "valid_split_payment", late_sellers
        if is_within and reconciled:
            return "unsupported_late_claim", late_sellers
        raise ValueError("raw case does not match policy")

    def _verify_evidence(
        self,
        order_id: str,
        items: list[Any],
        payments: list[Any],
        cause: str,
        evidence_ids: list[str],
        errors: list[str],
    ) -> None:
        allowed = {f"order:{order_id}", f"policy:{cause}"}
        allowed.update(
            f"item:{order_id}:{row['order_item_id']}" for row in items
        )
        allowed.update(
            f"payment:{order_id}:{row['payment_sequential']}" for row in payments
        )
        seller_ids = set(row["seller_id"] for row in items)
        allowed.update(f"seller:{seller_id}" for seller_id in seller_ids)
        if len(evidence_ids) != len(set(evidence_ids)):
            errors.append("evidence:duplicate")
        if any(evidence not in allowed for evidence in evidence_ids):
            errors.append("evidence:false_positive")
        if f"order:{order_id}" not in evidence_ids or f"policy:{cause}" not in evidence_ids:
            errors.append("evidence:missing_required")
        for evidence in evidence_ids:
            if not re.fullmatch(r"(?:order|seller|policy):[^:]+|(?:item|payment):[^:]+:[^:]+", evidence):
                errors.append("evidence:format")
                break
        if any(not self._repository.seller_exists(seller_id) for seller_id in seller_ids):
            errors.append("evidence:unknown_seller")

    @staticmethod
    def _as_float(value: Decimal) -> float:
        return float(value.quantize(Decimal("0.01")))
