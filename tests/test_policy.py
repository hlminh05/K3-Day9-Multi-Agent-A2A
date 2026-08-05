from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from ecommerce_dispute.agents.policy import PolicyAgent
from ecommerce_dispute.contracts import (
    CaseRequest,
    DeliveryHandoff,
    OrderSellerHandoff,
    PaymentHandoff,
    LLMReview,
)
from tests.fakes import FakeLLMClient


class PolicyAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = PolicyAgent(FakeLLMClient())
        self.review = LLMReview("qwen/qwen3-8b", "{}", True, 0.01)
        self.case = CaseRequest(
            "EC_TEST", "2018-01-01", "vi", "test", "order", "EC_POLICY_V1"
        )

    def order(self, status: str = "delivered", late_sellers: tuple[str, ...] = ()):
        return OrderSellerHandoff(
            "order",
            status,
            datetime(2018, 1, 2),
            datetime(2018, 1, 5),
            datetime(2018, 1, 4),
            (),
            late_sellers,
            late_sellers,
            Decimal("100"),
            Decimal("15"),
            self.review,
        )

    def payment(self, *, split: bool = False, reconciled: bool = True):
        return PaymentHandoff(
            "order",
            (),
            Decimal("115"),
            Decimal("115"),
            Decimal("0"),
            reconciled,
            split,
            self.review,
        )

    def delivery(
        self, *, late: bool, within: bool, late_sellers: tuple[str, ...] = ()
    ):
        return DeliveryHandoff(
            "order",
            datetime(2018, 1, 5),
            datetime(2018, 1, 4),
            late,
            within,
            late_sellers,
            self.review,
        )

    def test_canceled_has_priority_over_late_delivery(self):
        decision = self.agent.decide(
            self.case,
            self.order("canceled", ("seller",)),
            self.payment(),
            self.delivery(late=True, within=False, late_sellers=("seller",)),
        )
        self.assertEqual("canceled_order_paid", decision.primary_issue)
        self.assertEqual(Decimal("115"), decision.recommended_refund)

    def test_unavailable_paid(self):
        decision = self.agent.decide(
            self.case,
            self.order("unavailable"),
            self.payment(),
            self.delivery(late=False, within=False),
        )
        self.assertEqual("unavailable_order_paid", decision.primary_issue)

    def test_late_delivery_seller(self):
        decision = self.agent.decide(
            self.case,
            self.order(late_sellers=("seller",)),
            self.payment(),
            self.delivery(late=True, within=False, late_sellers=("seller",)),
        )
        self.assertEqual("late_delivery_seller", decision.primary_issue)
        self.assertEqual("seller", decision.responsible_parties[0].party_type)
        self.assertEqual(Decimal("15"), decision.recommended_refund)

    def test_late_delivery_logistics(self):
        decision = self.agent.decide(
            self.case,
            self.order(),
            self.payment(),
            self.delivery(late=True, within=False),
        )
        self.assertEqual("late_delivery_logistics", decision.primary_issue)

    def test_valid_split_payment_precedes_unsupported_claim(self):
        decision = self.agent.decide(
            self.case,
            self.order(),
            self.payment(split=True),
            self.delivery(late=False, within=True),
        )
        self.assertEqual("valid_split_payment", decision.primary_issue)
        self.assertEqual("no_action", decision.case_status)

    def test_unsupported_late_claim(self):
        decision = self.agent.decide(
            self.case,
            self.order(),
            self.payment(),
            self.delivery(late=False, within=True),
        )
        self.assertEqual("unsupported_late_claim", decision.primary_issue)

    def test_unknown_policy_is_rejected(self):
        invalid = CaseRequest("X", "", "vi", "", "order", "EC_POLICY_V2")
        with self.assertRaisesRegex(ValueError, "Unsupported policy"):
            self.agent.decide(
                invalid,
                self.order(),
                self.payment(),
                self.delivery(late=False, within=True),
            )


if __name__ == "__main__":
    unittest.main()
