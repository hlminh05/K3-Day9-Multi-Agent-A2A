"""End-to-end runner and the sole owner of artifact writes."""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agents import DeliveryAgent, OrderSellerAgent, PaymentAgent, PolicyAgent, VerifierAgent
from .config import (
    FRAMEWORK,
    MODEL_NAME,
    MODEL_MAX_ALLOWED_BILLION,
    MODEL_PARAMETER_SIZE_BILLION,
    MODEL_PROVIDER,
    POLICY_VERSION,
)
from .coordinator import CoordinatorAgent
from .env import load_dotenv
from .llm import ModelGateway, OpenRouterClient
from .repository import OlistRepository
from .tracing import TraceRecorder


EXPECTED_CASE_NAMES = tuple(f"EC_{index:03d}.json" for index in range(1, 51))
AGENT_NAMES = (
    "coordinator_agent",
    "order_seller_agent",
    "payment_agent",
    "delivery_agent",
    "policy_agent",
    "verifier_agent",
)


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_cases(input_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    names = tuple(path.name for path in sorted(input_dir.glob("EC_*.json")))
    if names != EXPECTED_CASE_NAMES:
        missing = sorted(set(EXPECTED_CASE_NAMES) - set(names))
        extra = sorted(set(names) - set(EXPECTED_CASE_NAMES))
        raise ValueError(f"Input hard gate failed; missing={missing}, extra={extra}")
    cases: list[tuple[str, dict[str, Any]]] = []
    for name in names:
        payload = json.loads((input_dir / name).read_text(encoding="utf-8"))
        if payload.get("case_id") != name.removesuffix(".json"):
            raise ValueError(f"Case ID does not match filename: {name}")
        cases.append((name, payload))
    return cases


def run_pipeline(
    project_root: Path | str = Path.cwd(),
    *,
    output_dir: Path | None = None,
    trace_path: Path | None = None,
    metadata_path: Path | None = None,
    llm_client: ModelGateway | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    outputs_path = output_dir or root / "output"
    trace_file = trace_path or root / "trace.jsonl"
    metadata_file = metadata_path or root / "metadata.json"

    load_dotenv(root / ".env")
    if MODEL_PARAMETER_SIZE_BILLION > MODEL_MAX_ALLOWED_BILLION:
        raise ValueError(
            f"Model hard gate failed: {MODEL_PARAMETER_SIZE_BILLION}B > "
            f"{MODEL_MAX_ALLOWED_BILLION}B"
        )
    llm = llm_client or OpenRouterClient()
    if isinstance(llm, OpenRouterClient):
        llm.assert_ready()

    repository = OlistRepository(root / "data")
    trace = TraceRecorder()
    coordinator = CoordinatorAgent(
        OrderSellerAgent(repository, llm),
        PaymentAgent(repository, llm),
        DeliveryAgent(llm),
        PolicyAgent(llm),
        VerifierAgent(repository, llm),
        llm,
        trace,
    )

    # Resolve and verify every case in memory first. No partial submission is written.
    resolved: list[tuple[str, dict[str, Any]]] = []
    cases = _load_cases(root / "input")
    for index, (filename, raw_case) in enumerate(cases, start=1):
        resolved.append((filename, coordinator.resolve(raw_case)))
        if progress_callback and (index == 1 or index % 5 == 0 or index == len(cases)):
            progress_callback(
                f"Resolved {index}/{len(cases)} cases; "
                f"model_calls={llm.stats().get('model_calls', 0)}"
            )

    outputs_path.mkdir(parents=True, exist_ok=True)
    for filename, output in resolved:
        _atomic_json(outputs_path / filename, output)
    trace_file.parent.mkdir(parents=True, exist_ok=True)
    trace.write_latest(trace_file)

    distribution = Counter(
        output["assessment"]["primary_issue"] for _, output in resolved
    )
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": POLICY_VERSION,
        "model": {
            "name": MODEL_NAME,
            "provider": MODEL_PROVIDER,
            "parameter_size_billion": MODEL_PARAMETER_SIZE_BILLION,
            "usage": "Qwen3 API reviews every agent handoff; deterministic guardrails verify facts",
            "within_10b_limit": MODEL_PARAMETER_SIZE_BILLION
            <= MODEL_MAX_ALLOWED_BILLION,
            "required": True,
        },
        "agents": [
            {
                "name": name,
                "model": MODEL_NAME,
                "parameter_size_billion": MODEL_PARAMETER_SIZE_BILLION,
            }
            for name in AGENT_NAMES
        ],
        "framework": FRAMEWORK,
        "runtime": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "run": {
            "run_id": trace.run_id,
            "case_count": len(resolved),
            "trace_event_count": trace.event_count,
            "issue_distribution": dict(sorted(distribution.items())),
            "llm": llm.stats(),
        },
    }
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(metadata_file, metadata)
    return metadata


def create_submission_zip(output_dir: Path, destination: Path) -> None:
    files = sorted(output_dir.glob("EC_*.json"))
    if tuple(path.name for path in files) != EXPECTED_CASE_NAMES:
        raise ValueError("Output ZIP hard gate failed: expected exactly EC_001..EC_050")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    temporary.replace(destination)
