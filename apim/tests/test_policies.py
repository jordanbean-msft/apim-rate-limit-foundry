"""Offline rendered-policy contracts; live gateway expression acceptance is separate."""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "authority": "https://login.microsoftonline.us",
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "api_audience": "api://00000000-0000-0000-0000-000000000002",
    "api_client_id": "00000000-0000-0000-0000-000000000002",
    "gateway_client_id": "00000000-0000-0000-0000-000000000003",
    "function_client_id": "00000000-0000-0000-0000-000000000004",
    "function_principal_id": "00000000-0000-0000-0000-000000000005",
    "function_url": "https://limiter.azurewebsites.us",
    "stream_url": "https://stream.azurewebsites.us",
    "streaming_enabled": "true",
    "web_url": "https://portal.azurewebsites.us",
    "audiences": "<audience>api://client</audience>",
    "burst_calls": "60",
    "burst_seconds": "60",
    "send_request_timeout": "10",
    "max_body_bytes": "1048576",
    "llm_tokens_per_minute": "100000",
    "api_protocol": "openai-chat",
    "legacy_default_alias": "sample-model",
    "admission": "",
    "llm_policy": "",
    "model_registry": json.dumps(
        {
            "openai-chat:sample-model": {
                "api_protocol": "openai-chat",
                "endpoint": "https://sample.openai.azure.us",
                "path": "/openai/deployments/provider-chat/chat/completions",
                "model": "provider-chat",
                "audience": "https://cognitiveservices.azure.us",
                "api_version": "2024-10-21",
                "price_version": "price-v1",
                "max_input_tokens": 64000,
                "max_output_tokens": 2048,
            }
        }
    ).replace('"', '\\"'),
}


def render(path: str, **values: str) -> str:
    """Render scalar Terraform substitutions without credentials or network calls."""
    variables = PARAMETERS | values
    content = (ROOT / path).read_text()
    return re.sub(r"\$\{([a-z_]+)\}", lambda match: variables[match.group(1)], content)


def inference(protocol: str = "openai-chat") -> ET.Element:
    """Render a complete operation with its selected admission and native burst guard."""
    admission = "foundry" if protocol == "openai-chat" else "responses"
    return ET.fromstring(
        render(
            "policies/ai.xml.tftpl",
            api_protocol=protocol,
            admission=render(f"policies/{admission}-admission.xml.tftpl"),
            llm_policy=render("policies/llm-limit.xml.tftpl"),
        )
    )


class GatewayPolicyTests(unittest.TestCase):
    def test_all_deployed_templates_render_as_xml(self) -> None:
        for path in ROOT.glob("*/*.xml.tftpl"):
            with self.subTest(path=path):
                content = render(str(path.relative_to(ROOT)))
                if path.name in {
                    "foundry-admission.xml.tftpl",
                    "responses-admission.xml.tftpl",
                    "llm-limit.xml.tftpl",
                }:
                    content = f"<fragment>{content}</fragment>"
                ET.fromstring(content)
        inference("openai-responses")

    def test_person_budget_identity_never_falls_back_to_an_application(self) -> None:
        identity = render("fragments/identity.xml.tftpl")
        root = ET.fromstring(identity)
        principal = root.find("./set-variable[@name='principal-id']").get("value")
        self.assertIn('"oid"', principal)
        self.assertNotIn('"azp"', principal)
        rejection = next(node for node in root.findall(".//when") if "scp" in node.get("condition"))
        self.assertIn('"idtyp"', rejection.get("condition"))
        self.assertIn('"app"', rejection.get("condition"))
        self.assertEqual(rejection.find("./return-response/set-status").get("code"), "401")
        self.assertNotIn("X-User", identity)

    def test_inference_still_requires_product_key_and_validated_entra_token(self) -> None:
        root = ET.fromstring(render("fragments/identity.xml.tftpl"))
        self.assertIsNotNone(root.find("./validate-jwt/required-claims/claim[@name='tid']"))
        condition = root.find("./choose/when").get("condition")
        self.assertIn("context.Product == null", condition)
        self.assertIn("Ocp-Apim-Subscription-Key", condition)

    def test_native_rpm_tpm_protect_before_monthly_check(self) -> None:
        root = inference()
        inbound = list(root.find("inbound"))
        native = root.find("./inbound/llm-token-limit")
        check = root.find("./inbound/include-fragment[@fragment-id='limiter-budget-check']")
        self.assertLess(inbound.index(native), inbound.index(check))
        rpm = ET.fromstring(render("fragments/identity.xml.tftpl")).find("rate-limit-by-key")
        self.assertIn('"subscription-id"', rpm.get("counter-key"))

    def test_budget_check_propagates_only_trusted_identity_and_no_estimates(self) -> None:
        root = ET.fromstring(render("fragments/budget-check.xml.tftpl"))
        call = root.find("./send-request")
        self.assertTrue(call.findtext("set-url").endswith("/api/budgets/check"))
        body = call.findtext("set-body")
        fields = set(re.findall(r'new JProperty\("([^"]+)"', body))
        self.assertEqual(
            fields,
            {
                "request_id",
                "tenant_id",
                "principal_id",
                "subscription_id",
                "model",
                "api_protocol",
                "streaming",
            },
        )
        self.assertIsNotNone(call.find("authentication-managed-identity"))
        self.assertIn('["request_id"] !=', render("fragments/budget-check.xml.tftpl"))
        self.assertIsNotNone(root.find(".//set-status[@code='503']"))
        self.assertIsNotNone(root.find(".//set-status[@code='429']"))
        self.assertIsNotNone(
            root.find(".//return-response[@response-variable-name='budget-response']")
        )

    def test_streams_force_terminal_usage_without_reading_response_body(self) -> None:
        root = inference()
        body = root.findtext("./inbound/set-body")
        self.assertIn('new JProperty("include_usage", true)', body)
        forward = root.find("./backend/forward-request")
        self.assertEqual(forward.get("buffer-response"), "false")
        streaming = next(
            node
            for node in root.findall("./inbound/choose/when")
            if node.find("set-backend-service") is not None
        )
        self.assertEqual(streaming.find("rewrite-uri").get("template"), "/api/stream")
        self.assertIsNotNone(streaming.find("./set-header[@name='X-Usage-Request-ID']"))
        nonstream = root.find("./outbound/choose/when")
        self.assertIn('!(bool)context.Variables["streaming"]', nonstream.get("condition"))
        self.assertIn("preserveContent: true", nonstream.find("set-variable").get("value"))

    def test_direct_backend_uses_preserved_entities_and_managed_identity(self) -> None:
        root = inference()
        backend = root.find(".//set-backend-service[@backend-id]")
        self.assertIn('"model-backend-id"', backend.get("backend-id"))
        lookup = render("fragments/model-lookup.xml.tftpl")
        self.assertIn('"ai-model-" + hash.Substring(0, 12)', lookup)
        self.assertIsNotNone(root.find(".//authentication-managed-identity"))

    def test_record_uses_provider_object_unknown_is_explicit_and_no_cost_math(self) -> None:
        text = render("fragments/usage-record.xml.tftpl")
        root = ET.fromstring(text)
        call = root.find("send-request")
        self.assertTrue(call.findtext("set-url").endswith("/api/usage/record"))
        body = call.findtext("set-body")
        self.assertIn('usage == null ? "usage_unknown" : "actual"', body)
        self.assertIn('record["provider_usage"] = usage', body)
        for forbidden in ("cost_micro_usd", "cached_input_tokens", "input_per_million"):
            self.assertNotIn(forbidden, body)

    def test_only_new_durable_events_are_logged_with_stable_private_partition(self) -> None:
        root = ET.fromstring(render("fragments/usage-record.xml.tftpl"))
        success = root.find("./choose/when")
        self.assertIn("StatusCode == 200", success.get("condition"))
        new_record = success.find("./choose/when")
        self.assertIn('["replayed"] == false', new_record.get("condition"))
        event = new_record.find("set-variable")
        self.assertIn('["event"]', event.get("value"))
        logger = new_record.find(".//log-to-eventhub")
        self.assertIn('["tenant_ref"]', logger.get("partition-key"))
        self.assertIn('["user_ref"]', logger.get("partition-key"))

    def test_accounting_or_publish_failure_preserves_provider_response(self) -> None:
        root = inference()
        fallback = root.find("./on-error/choose/when/return-response")
        self.assertIn('"provider-status"', fallback.find("set-status").get("code"))
        self.assertIn('"provider-body"', fallback.findtext("set-body"))
        call = ET.fromstring(render("fragments/usage-record.xml.tftpl")).find("send-request")
        self.assertEqual(call.get("ignore-error"), "true")
        self.assertNotIn("retry", ET.tostring(root, encoding="unicode"))

    def test_internal_callback_is_function_workload_only_and_does_not_forward(self) -> None:
        root = ET.fromstring(render("policies/usage-events.xml.tftpl"))
        claims = {
            claim.get("name"): claim.findtext("value")
            for claim in root.findall("./inbound/validate-jwt/required-claims/claim")
        }
        self.assertEqual(claims["oid"], PARAMETERS["function_principal_id"])
        self.assertEqual(claims["azp"], PARAMETERS["function_client_id"])
        self.assertEqual(claims["roles"], "RateLimit.Gateway")
        self.assertIn('"scp"', root.find("./inbound/choose/when").get("condition"))
        self.assertIsNotNone(root.find("./inbound/log-to-eventhub"))
        self.assertIsNone(root.find(".//forward-request"))
        self.assertEqual(root.find("./inbound/return-response/set-status").get("code"), "204")
        self.assertIn(
            "16384", root.find("./inbound/set-variable[@name='valid-event']").get("value")
        )

    def test_obsolete_policy_artifacts_are_removed(self) -> None:
        names = {path.name for path in ROOT.glob("*/*.xml.tftpl")}
        for removed in ("reserve", "settle", "anthropic", "document", "language"):
            self.assertFalse(any(removed in name for name in names), removed)
