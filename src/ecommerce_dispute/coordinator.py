"""Single coordinator governing all subordinate agents and handoffs."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from .agents import DeliveryAgent, OrderSellerAgent, PaymentAgent, PolicyAgent, VerifierAgent
from .config import MAX_ENTITY_IDS, MAX_EVIDENCE_IDS
from .contracts import CaseRequest, OrderSellerHandoff, PaymentHandoff, PolicyDecision
from .llm import ModelGateway, review
from .tracing import TraceRecorder


class CoordinatorAgent:
    name = "coordinator_agent"

    def __init__(
        self,
        order_seller: OrderSellerAgent,
        payment: PaymentAgent,
        delivery: DeliveryAgent,
        policy: PolicyAgent,
        verifier: VerifierAgent,
        llm: ModelGateway,
        trace: TraceRecorder,
    ) -> None:
        self._order_seller = order_seller
        self._payment = payment
        self._delivery = delivery
        self._policy = policy
        self._verifier = verifier
        self._llm = llm
        self._trace = trace

    def resolve(self, raw_case: dict[str, Any]) -> dict[str, Any]:
        case = CaseRequest.from_dict(raw_case)
        self._trace.record(
            case.case_id,
            "input_reader",
            self.name,
            "case_received",
            {"order_id": case.order_id, "policy_version": case.policy_version},
        )

        expected_route = [
            "order_seller_agent",
            "payment_agent",
            "delivery_agent",
            "policy_agent",
            "verifier_agent",
        ]
        route_call = self._llm.invoke(
            agent_name=self.name,
            system_prompt=(
                "Plan the safe worker route for an e-commerce dispute. Respect the supplied "
                "dependency order and keep artifact_writer after verifier."
            ),
            payload={
                "customer_language": case.language,
                "workflow_type": "olist_ecommerce_dispute",
                "required_dependency_order": expected_route,
            },
            schema={
                "type": "object",
                "properties": {
                    "route": {"type": "array", "items": {"type": "string"}},
                    "customer_intent": {"type": "string"},
                    "coordination_note": {"type": "string"},
                },
                "required": ["route", "customer_intent", "coordination_note"],
            },
        )
        route_review = review(
            route_call, {"route": expected_route}, self._llm.model_name
        )
        self._trace.record(
            case.case_id,
            self.name,
            "trace_recorder",
            "coordination_plan",
            asdict(route_review),
        )

        self._assign(case, self._order_seller.name, "investigate_order_seller")
        order = self._order_seller.investigate(case.order_id)
        self._handoff(case, self._order_seller.name, "order_seller_handoff", order)

        self._assign(case, self._payment.name, "reconcile_payments")
        payment = self._payment.reconcile(order)
        self._handoff(case, self._payment.name, "payment_handoff", payment)

        self._assign(case, self._delivery.name, "assess_delivery")
        delivery = self._delivery.assess(order)
        self._handoff(case, self._delivery.name, "delivery_handoff", delivery)

        self._assign(case, self._policy.name, "apply_policy")
        decision = self._policy.decide(case, order, payment, delivery)
        self._handoff(case, self._policy.name, "policy_handoff", decision)

        draft = self._assemble(case, order, payment, decision)
        self._trace.record(
            case.case_id,
            self.name,
            self._verifier.name,
            "verification_request",
            {"primary_issue": decision.primary_issue},
        )
        verification = self._verifier.verify(case, draft)
        self._handoff(case, self._verifier.name, "verification_handoff", verification)
        if not verification.accepted:
            raise ValueError(
                f"Verifier rejected {case.case_id}: {', '.join(verification.errors)}"
            )
        self._trace.record(
            case.case_id,
            self.name,
            "artifact_writer",
            "approved_output",
            {"case_id": case.case_id, "verified": True},
        )
        return draft

    def _assign(self, case: CaseRequest, receiver: str, task: str) -> None:
        self._trace.record(
            case.case_id,
            self.name,
            receiver,
            "task_assignment",
            {"task": task, "order_id": case.order_id},
        )

    def _handoff(self, case: CaseRequest, sender: str, kind: str, handoff: Any) -> None:
        self._trace.record(
            case.case_id,
            sender,
            self.name,
            kind,
            asdict(handoff),
        )

    @staticmethod
    def _assemble(
        case: CaseRequest,
        order: OrderSellerHandoff,
        payment: PaymentHandoff,
        decision: PolicyDecision,
    ) -> dict[str, Any]:
        item_ids = [
            f"{case.order_id}:{item.order_item_id}"
            for item in order.items[:MAX_ENTITY_IDS]
        ]
        payment_ids = [
            f"{case.order_id}:{row.payment_sequential}"
            for row in payment.payments[:MAX_ENTITY_IDS]
        ]
        seller_ids = list(order.seller_ids[:MAX_ENTITY_IDS])

        evidence = [f"order:{case.order_id}"]
        evidence.extend(
            f"item:{case.order_id}:{item.order_item_id}" for item in order.items
        )
        evidence.extend(
            f"payment:{case.order_id}:{row.payment_sequential}"
            for row in payment.payments
        )
        evidence.extend(f"seller:{seller_id}" for seller_id in order.seller_ids)
        policy_evidence = f"policy:{decision.cause_code}"
        evidence = list(dict.fromkeys(evidence))[: MAX_EVIDENCE_IDS - 1]
        evidence.append(policy_evidence)

        return {
            "case_id": case.case_id,
            "assessment": {
                "primary_issue": decision.primary_issue,
                "case_status": decision.case_status,
                "confidence": decision.confidence,
            },
            "affected_entities": {
                "order_ids": [case.order_id],
                "item_ids": item_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_ids,
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": decision.cause_code, "rank": 1}],
                "responsible_parties": [
                    {"party_type": party.party_type, "party_id": party.party_id}
                    for party in decision.responsible_parties
                ],
            },
            "evidence_ids": evidence,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": CoordinatorAgent._money(order.item_total),
                "freight_total_brl": CoordinatorAgent._money(order.freight_total),
                "payment_total_brl": CoordinatorAgent._money(payment.payment_total),
                "recommended_refund_brl": CoordinatorAgent._money(
                    decision.recommended_refund
                ),
            },
            "resolution_actions": [decision.action],
        }

    @staticmethod
    def _money(value: Decimal) -> float:
        return float(value.quantize(Decimal("0.01")))
