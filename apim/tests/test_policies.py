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
                "backend_id": "ai-model-0123456789ab",
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
        self.assertIn(
            'context.Request.Headers.GetValueOrDefault("traceparent", "")',
            call.findtext("set-header[@name='traceparent']/value"),
        )
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
        forward = root.find("./backend/choose/otherwise/forward-request")
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
        self.assertIn('["backend_id"]', lookup)
        self.assertNotIn("SHA256", lookup)
        self.assertIsNotNone(root.find(".//authentication-managed-identity"))

    def test_request_and_registry_are_parsed_once(self) -> None:
        body = render("policies/ai.xml.tftpl")
        lookup = render("fragments/model-lookup.xml.tftpl")
        self.assertEqual(body.count("JToken.Parse"), 1)
        self.assertEqual(lookup.count("JObject.Parse"), 1)
        self.assertNotIn("JObject.Parse((string)context.Variables[", lookup)

    def test_pooled_alias_is_a_flag_on_the_registry_entry(self) -> None:
        lookup = ET.fromstring(render("fragments/model-lookup.xml.tftpl"))
        pooled = lookup.find("./set-variable[@name='model-pooled']").get("value")
        self.assertIn('["pool"]', pooled)

    def test_only_nonstreaming_pooled_requests_retry_on_throttle_or_server_error(self) -> None:
        root = inference()
        backend = root.find("./backend/choose")
        retry_branch = backend.find("./when")
        self.assertIn('"streaming"', retry_branch.get("condition"))
        self.assertIn('"model-pooled"', retry_branch.get("condition"))
        retry = retry_branch.find("retry")
        self.assertIn("429", retry.get("condition"))
        self.assertIn(">= 500", retry.get("condition").replace("&gt;", ">"))
        self.assertLessEqual(int(retry.get("count")), 2)
        self.assertEqual(retry.get("first-fast-retry"), "true")
        self.assertEqual(retry.find("forward-request").get("buffer-request-body"), "true")
        self.assertEqual(len(root.findall(".//retry")), 1)

    def test_retry_never_wraps_admission_budget_or_usage_recording(self) -> None:
        root = inference()
        retry = root.find("./backend//retry")
        self.assertEqual([child.tag for child in retry], ["forward-request"])
        self.assertIsNone(root.find("./inbound//retry"))
        self.assertIsNone(root.find("./outbound//retry"))
        self.assertIsNone(root.find("./on-error//retry"))

    def test_provider_error_responses_are_not_charged(self) -> None:
        outbound = inference().find("outbound")
        gate = outbound.find("./choose/when")
        self.assertIn("context.Response.StatusCode", gate.get("condition"))
        self.assertIn("< 400", gate.get("condition"))
        self.assertIsNotNone(gate.find("include-fragment"))

    def test_record_uses_provider_object_unknown_is_explicit_and_no_cost_math(self) -> None:
        text = render("fragments/usage-record.xml.tftpl")
        root = ET.fromstring(text)
        call = root.find("send-request")
        self.assertTrue(call.findtext("set-url").endswith("/api/usage/record"))
        body = call.findtext("set-body")
        self.assertIn('usage == null ? "usage_unknown" : "actual"', body)
        self.assertIn('record["provider_usage"] = usage', body)
        self.assertIn(
            'context.Request.Headers.GetValueOrDefault("traceparent", "")',
            call.findtext("set-header[@name='traceparent']/value"),
        )
        for forbidden in ("cost_micro_usd", "cached_input_tokens", "input_per_million"):
            self.assertNotIn(forbidden, body)

    def test_apim_reports_redis_acceptance_but_never_publishes_events(self) -> None:
        root = ET.fromstring(render("fragments/usage-record.xml.tftpl"))
        success = root.find("./choose/when")
        self.assertIn("StatusCode == 200", success.get("condition"))
        self.assertEqual(
            success.findtext("./set-header[@name='X-RateLimit-Accounting']/value"),
            "redis-accepted",
        )
        self.assertEqual(
            root.findtext("./choose/otherwise/set-header[@name='X-RateLimit-Accounting']/value"),
            "unavailable",
        )
        self.assertIsNone(root.find(".//log-to-eventhub"))
        self.assertEqual(
            inference().findtext("./outbound/set-header[@name='X-RateLimit-Persistence']/value"),
            "best-effort",
        )

    def test_gateway_failure_after_admission_is_recorded_as_unknown_usage(self) -> None:
        root = inference()
        recovery = root.find("./on-error/choose/when")
        self.assertIn('"budget-checked"', recovery.get("condition"))
        self.assertIn('"provider-body"', recovery.get("condition"))
        self.assertEqual(recovery.find("set-variable").get("value"), "{}")
        self.assertIsNotNone(recovery.find("include-fragment[@fragment-id='limiter-usage-record']"))
        self.assertIsNone(root.find("./on-error//return-response"))
        call = ET.fromstring(render("fragments/usage-record.xml.tftpl")).find("send-request")
        self.assertEqual(call.get("ignore-error"), "true")
        for section in ("inbound", "outbound", "on-error"):
            self.assertNotIn("retry", ET.tostring(root.find(section), encoding="unicode"))

    def test_caller_credentials_are_stripped_after_the_budget_check(self) -> None:
        root = inference()
        inbound = list(root.find("inbound"))
        check = root.find("./inbound/include-fragment[@fragment-id='limiter-budget-check']")
        strip = root.find("./inbound/include-fragment[@fragment-id='limiter-strip-caller-headers']")
        self.assertLess(inbound.index(check), inbound.index(strip))
        deleted = {
            node.get("name")
            for node in ET.fromstring(render("fragments/strip-caller-headers.xml.tftpl")).findall(
                "set-header[@exists-action='delete']"
            )
        }
        self.assertTrue({"Authorization", "Ocp-Apim-Subscription-Key", "api-key"} <= deleted)

    def test_portal_browser_preflight_allows_w3c_correlation(self) -> None:
        root = ET.fromstring(render("policies/portal.xml.tftpl"))
        headers = {
            node.text.lower() for node in root.findall("./inbound/cors/allowed-headers/header")
        }
        self.assertTrue({"traceparent", "tracestate", "x-correlation-id"} <= headers)
        self.assertNotIn("*", headers)

    def test_obsolete_policy_artifacts_are_removed(self) -> None:
        names = {path.name for path in ROOT.glob("*/*.xml.tftpl")}
        for removed in ("reserve", "settle", "anthropic", "document", "language", "usage-events"):
            self.assertFalse(any(removed in name for name in names), removed)
