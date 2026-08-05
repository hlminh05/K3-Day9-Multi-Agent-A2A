from __future__ import annotations

import json
import re
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from ecommerce_dispute.agents.verifier import VerifierAgent
from ecommerce_dispute.config import MODEL_PARAMETER_SIZE_BILLION
from ecommerce_dispute.contracts import CaseRequest
from ecommerce_dispute.pipeline import create_submission_zip, run_pipeline
from ecommerce_dispute.repository import OlistRepository
from tests.fakes import FakeLLMClient


ROOT = Path(__file__).resolve().parents[1]


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.temp_root = Path(cls.temporary.name)
        cls.output = cls.temp_root / "output"
        cls.trace = cls.temp_root / "trace.jsonl"
        cls.metadata_path = cls.temp_root / "metadata.json"
        cls.logging_dir = cls.temp_root / "logging"
        cls.fake_llm = FakeLLMClient()
        cls.metadata = run_pipeline(
            ROOT,
            output_dir=cls.output,
            trace_path=cls.trace,
            metadata_path=cls.metadata_path,
            logging_dir=cls.logging_dir,
            llm_client=cls.fake_llm,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_exactly_50_outputs(self):
        self.assertEqual(
            [f"EC_{number:03d}.json" for number in range(1, 51)],
            [path.name for path in sorted(self.output.glob("*.json"))],
        )

    def test_expected_policy_distribution(self):
        issues = Counter(
            json.loads(path.read_text(encoding="utf-8"))["assessment"]["primary_issue"]
            for path in self.output.glob("*.json")
        )
        self.assertEqual(
            {
                "canceled_order_paid": 8,
                "late_delivery_logistics": 8,
                "late_delivery_seller": 8,
                "unavailable_order_paid": 8,
                "unsupported_late_claim": 9,
                "valid_split_payment": 9,
            },
            dict(issues),
        )

    def test_each_case_has_real_coordinator_worker_trace(self):
        events = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(650, len(events))
        for case_number in range(1, 51):
            case_id = f"EC_{case_number:03d}"
            case_events = [event for event in events if event["case_id"] == case_id]
            self.assertEqual(13, len(case_events))
            senders = {event["sender"] for event in case_events}
            self.assertTrue(
                {
                    "order_seller_agent",
                    "payment_agent",
                    "delivery_agent",
                    "policy_agent",
                    "verifier_agent",
                }.issubset(senders)
            )

    def test_verifier_rejects_fake_evidence(self):
        raw_case = json.loads((ROOT / "input/EC_001.json").read_text(encoding="utf-8"))
        case = CaseRequest.from_dict(raw_case)
        output = json.loads((self.output / "EC_001.json").read_text(encoding="utf-8"))
        output["evidence_ids"].append("payment:not-a-real-order:99")
        result = VerifierAgent(
            OlistRepository(ROOT / "data"), FakeLLMClient()
        ).verify(case, output)
        self.assertFalse(result.accepted)
        self.assertIn("evidence:false_positive", result.errors)

    def test_model_limit(self):
        self.assertLessEqual(MODEL_PARAMETER_SIZE_BILLION, 10)
        self.assertTrue(self.metadata["model"]["within_10b_limit"])

    def test_every_agent_invokes_qwen_gateway(self):
        self.assertEqual(300, self.metadata["run"]["llm"]["model_calls"])
        self.assertEqual("qwen/qwen3-8b", self.metadata["model"]["name"])

    def test_logging_mirrors_canonical_artifacts(self):
        self.assertEqual(
            self.trace.read_bytes(), (self.logging_dir / "trace.jsonl").read_bytes()
        )
        self.assertEqual(
            self.metadata_path.read_bytes(),
            (self.logging_dir / "metadata.json").read_bytes(),
        )

    def test_api_payloads_are_anonymized(self):
        forbidden_keys = {
            "case_id",
            "order_id",
            "customer_message",
            "seller_id",
            "payment_values_brl",
            "item_total_brl",
            "freight_total_brl",
            "payment_total_brl",
            "delivered_carrier_date",
            "delivered_customer_date",
            "estimated_delivery_date",
            "shipping_limit_date",
            "evidence_ids",
        }
        for agent_name, payload in self.fake_llm.payloads:
            self.assertTrue(forbidden_keys.isdisjoint(payload), agent_name)
            serialized = json.dumps(payload, sort_keys=True)
            self.assertIsNone(re.search(r"\b[0-9a-f]{32}\b", serialized), agent_name)

    def test_submission_zip_has_only_50_json_files(self):
        destination = self.temp_root / "submission.zip"
        create_submission_zip(self.output, destination)
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
        self.assertEqual(
            [f"output/EC_{number:03d}.json" for number in range(1, 51)], names
        )


if __name__ == "__main__":
    unittest.main()
