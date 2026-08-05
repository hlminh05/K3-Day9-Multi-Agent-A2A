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
        self.payloads: list[tuple[str, dict[str, Any]]] = []

    def invoke(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> LLMCallResult:
        self.calls += 1
        self.payloads.append((agent_name, payload))
        if agent_name == "coordinator_agent":
            content = {
                "route": payload["required_dependency_order"],
                "customer_intent": "investigate dispute",
                "coordination_note": "dependency order accepted",
            }
        elif agent_name == "order_seller_agent":
            content = {
                "late_seller_count": payload["late_seller_count"],
                "finding": "checked",
            }
        elif agent_name == "payment_agent":
            content = {
                "is_reconciled": Decimal(payload["absolute_difference_brl"])
                <= Decimal(payload["tolerance_brl"]),
                "is_split_payment": payload["payment_row_count"] >= 2,
                "finding": "checked",
            }
        elif agent_name == "delivery_agent":
            content = {
                "is_late": payload["actual_after_estimate"],
                "is_within_estimate": payload["actual_within_estimate"],
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
        if status == "canceled" and payload["payment_positive"]:
            issue, cause, refund_basis, action = (
                "canceled_order_paid",
                "ORDER_CANCELED_AFTER_PAYMENT",
                "full_payment",
                "issue_full_refund",
            )
        elif status == "unavailable" and payload["payment_positive"]:
            issue, cause, refund_basis, action = (
                "unavailable_order_paid",
                "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                "full_payment",
                "issue_full_refund",
            )
        elif payload["delivery_late"] and payload["late_seller_count"]:
            issue, cause, refund_basis, action = (
                "late_delivery_seller",
                "SELLER_HANDOFF_AFTER_LIMIT",
                "freight",
                "refund_freight",
            )
        elif payload["delivery_late"]:
            issue, cause, refund_basis, action = (
                "late_delivery_logistics",
                "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "freight",
                "refund_freight",
            )
        elif payload["split_payment"] and payload["payment_reconciled"]:
            issue, cause, refund_basis, action = (
                "valid_split_payment",
                "MULTIPLE_PAYMENTS_RECONCILED",
                "none",
                "explain_valid_split_payment",
            )
        else:
            issue, cause, refund_basis, action = (
                "unsupported_late_claim",
                "DELIVERY_WITHIN_ESTIMATE",
                "none",
                "reject_late_refund",
            )
        return {
            "primary_issue": issue,
            "cause_code": cause,
            "refund_basis": refund_basis,
            "action": action,
            "rationale": "policy checked",
        }
