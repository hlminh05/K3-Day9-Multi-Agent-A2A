"""Configuration intentionally committed for reproducible grading."""

POLICY_VERSION = "EC_POLICY_V1"
PAYMENT_TOLERANCE_BRL = "0.10"

# The model name is committed (not stored in .env) as required by the lab.
MODEL_NAME = "qwen/qwen3-8b"
MODEL_PARAMETER_SIZE_BILLION = 8.2
MODEL_MAX_ALLOWED_BILLION = 10.0
MODEL_PROVIDER = "openrouter"
MODEL_API_NAME = MODEL_NAME
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LLM_REQUIRED = True
FRAMEWORK = "hybrid-qwen3-openrouter-with-deterministic-guardrails"

MAX_ENTITY_IDS = 5
MAX_EVIDENCE_IDS = 10
MAX_ROOT_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_ACTIONS = 5
