from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from ecommerce_dispute.llm import LLMCallResult


class FakeLLMClient:
    """Fast deterministic model double; production never uses this client."""

    model_name = "qwen/qwen3-8b"

    def __init__(self) -> None:
        self.calls = 0

    def invoke(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> LLMCallResult:
        self.calls += 1
        if agent_name == "coordinator_agent":
            content = {
                "route": payload["required_dependency_order"],
                "customer_intent": "investigate dispute",
                "coordination_note": "dependency order accepted",
            }
        elif agent_name == "order_seller_agent":
            carrier = self._timestamp(payload["delivered_carrier_date"])
            late = []
            for item in payload["items"]:
                limit = self._timestamp(item["shipping_limit_date"])
                if carrier and limit and carrier > limit and item["seller_id"] not in late:
                    late.append(item["seller_id"])
            content = {"late_seller_ids": late, "finding": "checked"}
        elif agent_name == "payment_agent":
            paid = sum(Decimal(value) for value in payload["payment_values_brl"])
            expected = Decimal(payload["item_total_brl"]) + Decimal(
                payload["freight_total_brl"]
            )
            content = {
                "is_reconciled": abs(paid - expected)
                <= Decimal(payload["tolerance_brl"]),
                "is_split_payment": len(payload["payment_values_brl"]) >= 2,
                "finding": "checked",
            }
        elif agent_name == "delivery_agent":
            delivered = self._timestamp(payload["delivered_customer_date"])
            estimated = self._timestamp(payload["estimated_delivery_date"])
            content = {
                "is_late": bool(delivered and estimated and delivered > estimated),
                "is_within_estimate": bool(
                    delivered and estimated and delivered <= estimated
                ),
                "finding": "checked",
            }
        elif agent_name == "policy_agent":
            content = self._policy(payload)
        elif agent_name == "verifier_agent":
            content = {"accepted": True, "audit_note": "internally consistent"}
        else:
            raise AssertionError(f"Unexpected agent: {agent_name}")
        response_json = json.dumps(content, sort_keys=True)
        return LLMCallResult(content, response_json, 0.01, 1, 1)

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "fake-for-tests",
            "model_calls": self.calls,
            "total_duration_ms": round(self.calls * 0.01, 3),
            "prompt_tokens": self.calls,
            "completion_tokens": self.calls,
        }

    @staticmethod
    def _timestamp(value: str) -> datetime | None:
        if value in {"", "None"}:
            return None
        return datetime.fromisoformat(value)

    @staticmethod
    def _policy(payload: dict[str, Any]) -> dict[str, Any]:
        status = payload["order_status"]
        paid = Decimal(payload["payment_total_brl"])
        freight = Decimal(payload["freight_total_brl"])
        if status == "canceled" and paid > 0:
            issue, cause, refund, action = (
                "canceled_order_paid",
                "ORDER_CANCELED_AFTER_PAYMENT",
                paid,
                "issue_full_refund",
            )
        elif status == "unavailable" and paid > 0:
            issue, cause, refund, action = (
                "unavailable_order_paid",
                "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                paid,
                "issue_full_refund",
            )
        elif payload["delivery_late"] and payload["late_seller_ids"]:
            issue, cause, refund, action = (
                "late_delivery_seller",
                "SELLER_HANDOFF_AFTER_LIMIT",
                freight,
                "refund_freight",
            )
        elif payload["delivery_late"]:
            issue, cause, refund, action = (
                "late_delivery_logistics",
                "CARRIER_DELIVERED_AFTER_ESTIMATE",
                freight,
                "refund_freight",
            )
        elif payload["split_payment"] and payload["payment_reconciled"]:
            issue, cause, refund, action = (
                "valid_split_payment",
                "MULTIPLE_PAYMENTS_RECONCILED",
                Decimal("0"),
                "explain_valid_split_payment",
            )
        else:
            issue, cause, refund, action = (
                "unsupported_late_claim",
                "DELIVERY_WITHIN_ESTIMATE",
                Decimal("0"),
                "reject_late_refund",
            )
        return {
            "primary_issue": issue,
            "cause_code": cause,
            "recommended_refund_brl": str(refund),
            "action": action,
            "rationale": "policy checked",
        }
