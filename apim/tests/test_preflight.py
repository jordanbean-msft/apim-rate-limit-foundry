"""Verify the offline deployment capability gates without contacting Azure."""

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
            FOUNDRY_RESOURCE_ID="/subscriptions/test/accounts/foundry",
        )
        environment.update(overrides)
        return subprocess.run(
            ["sh", "-c", MOCK_CLI, "preflight-test", str(ROOT / "infra/scripts/preflight.sh")],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_openai_only_baseline_needs_no_removed_service_values(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preflight passed", result.stdout)

    def test_missing_event_hub_specification_is_fail_closed(self) -> None:
        result = self._run(EVENT_HUB_PARTITIONS="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EVENT_HUB_PARTITIONS", result.stderr)

    def test_cloud_origin_cannot_cross_sovereign_boundary(self) -> None:
        result = self._run(
            AZURE_CLOUD="AzureUSGovernment",
            ARM_ENVIRONMENT="usgovernment",
            FOUNDRY_TOKEN_AUDIENCE="https://cognitiveservices.azure.us",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected cloud", result.stderr)

    def test_government_responses_requires_explicit_capability_acceptance(self) -> None:
        for verified, expected in [("false", 1), ("true", 0)]:
            with self.subTest(verified=verified):
                result = self._run(
                    AZURE_CLOUD="AzureUSGovernment",
                    ARM_ENVIRONMENT="usgovernment",
                    FOUNDRY_ENDPOINT="https://sample.openai.azure.us",
                    FOUNDRY_TOKEN_AUDIENCE="https://cognitiveservices.azure.us",
                    ENABLE_RESPONSES="true",
                    RESPONSES_ENDPOINT="https://sample.openai.azure.us",
                    RESPONSES_TOKEN_AUDIENCE="https://cognitiveservices.azure.us",
                    RESPONSES_RESOURCE_ID="/subscriptions/test/accounts/responses",
                    RESPONSES_CAPABILITY_VERIFIED="true",
                    RESPONSES_BYTE_TOKENIZER_VERIFIED="true",
                    RESPONSES_GOVERNMENT_VERIFIED=verified,
                    RESPONSES_LOCATION="usgovvirginia",
                    RESPONSES_DEPLOYMENT_NAME="sample",
                    RESPONSES_PRICE_VERSION="v1",
                )
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_referenced_aliases_require_safe_origin_and_verified_private_path(self) -> None:
        model = {
            "api_protocol": "openai-chat",
            "resource_id": "/subscriptions/test/accounts/chat",
            "endpoint": "https://chat.openai.azure.com",
            "audience": "https://cognitiveservices.azure.com",
            "location": "eastus2",
            "deployment_name": "provider-fast",
            "price_version": "v1",
            "max_input_tokens": 64000,
            "max_output_tokens": 2048,
            "role_definition_name": "Cognitive Services OpenAI User",
            "capability_verified": True,
            "government_verified": False,
            "byte_tokenizer_verified": True,
            "private_endpoint_verified": True,
            "api_version": "2024-10-21",
        }
        for changes, expected in [
            ({}, 0),
            ({"endpoint": "https://chat.openai.azure.com/path?api-key=caller"}, 1),
            ({"api_protocol": "unsupported"}, 1),
            ({"capability_verified": False}, 1),
        ]:
            with self.subTest(changes=changes):
                result = self._run(LLM_MODELS=json.dumps({"openai-chat:fast": model | changes}))
                self.assertEqual(result.returncode, expected, result.stderr)
