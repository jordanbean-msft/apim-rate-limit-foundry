"""Exercise deployment capability gates without contacting Azure."""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOCK_CLI = """
az() {
  case "$*" in
    "cloud show --query name -o tsv") printf '%s\\n' "$AZURE_CLOUD" ;;
    "account show --query tenantId -o tsv") printf '%s\\n' "$AZURE_TENANT_ID" ;;
    *"--query properties.disableLocalAuth -o tsv") printf 'true\\n' ;;
    *"--query properties.publicNetworkAccess -o tsv") printf 'Disabled\\n' ;;
    *) return 0 ;;
  esac
}
. "$1"
"""


class PreflightTests(unittest.TestCase):
    def _run(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ | json.loads((ROOT / "infra/environment.example.json").read_text())
        environment.update(
            PUBLIC_NETWORK_ACCESS_ENABLED="true",
            FOUNDRY_ENDPOINT="https://sample.openai.azure.com",
            RESPONSES_RESOURCE_ID="/subscriptions/test/accounts/responses",
            RESPONSES_ENDPOINT="https://sample.openai.azure.com",
            RESPONSES_CAPABILITY_VERIFIED="true",
            RESPONSES_BYTE_TOKENIZER_VERIFIED="true",
            RESPONSES_TOKEN_AUDIENCE="https://ai.azure.com",
            RESPONSES_LOCATION="eastus2",
            RESPONSES_DEPLOYMENT_NAME="sample-model",
            RESPONSES_PRICE_VERSION="sample-v1",
            ANTHROPIC_RESOURCE_ID="/subscriptions/test/accounts/anthropic",
            ANTHROPIC_ENDPOINT="https://sample.services.ai.azure.com",
            ANTHROPIC_CAPABILITY_VERIFIED="true",
            ANTHROPIC_HARD_INPUT_CAP_VERIFIED="true",
            ANTHROPIC_INPUT_CAP_EVIDENCE="Verified full model input maximum TEST-123",
            ANTHROPIC_TOKEN_AUDIENCE="https://ai.azure.com",
            ANTHROPIC_LOCATION="eastus2",
            ANTHROPIC_DEPLOYMENT_NAME="sample-claude",
            ANTHROPIC_PRICE_VERSION="sample-v1",
        )
        environment.update(overrides)
        return subprocess.run(
            ["sh", "-c", MOCK_CLI, "preflight-test", str(ROOT / "infra/scripts/preflight.sh")],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_optional_protocols_disabled_require_no_provider_access(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preflight passed", result.stdout)

    def test_government_responses_needs_separate_availability_acceptance(self) -> None:
        for verified, expected in [("false", 1), ("true", 0)]:
            with self.subTest(verified=verified):
                result = self._run(
                    AZURE_CLOUD="AzureUSGovernment",
                    ARM_ENVIRONMENT="usgovernment",
                    FOUNDRY_ENDPOINT="https://sample.openai.azure.us",
                    FOUNDRY_TOKEN_AUDIENCE="https://cognitiveservices.azure.us",
                    ENABLE_RESPONSES="true",
                    RESPONSES_ENDPOINT="https://sample.openai.azure.us",
                    RESPONSES_GOVERNMENT_VERIFIED=verified,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected:
                    self.assertIn("Revalidate Responses Government", result.stderr)

    def test_government_messages_never_falls_back_to_commercial(self) -> None:
        result = self._run(
            AZURE_CLOUD="AzureUSGovernment",
            ARM_ENVIRONMENT="usgovernment",
            FOUNDRY_ENDPOINT="https://sample.openai.azure.us",
            FOUNDRY_TOKEN_AUDIENCE="https://cognitiveservices.azure.us",
            ENABLE_ANTHROPIC="true",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no cross-cloud fallback", result.stderr)

    def test_messages_full_context_must_fit_function_admission(self) -> None:
        for ceiling, expected in [("200000", 0), ("200001", 1), ("1.5", 1)]:
            with self.subTest(ceiling=ceiling):
                result = self._run(ENABLE_ANTHROPIC="true", ANTHROPIC_CONTEXT_INPUT_TOKENS=ceiling)
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_messages_hard_limit_requires_verification_evidence(self) -> None:
        result = self._run(ENABLE_ANTHROPIC="true", ANTHROPIC_INPUT_CAP_EVIDENCE="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recorded backend hard-context-cap verification", result.stderr)


if __name__ == "__main__":
    unittest.main()
