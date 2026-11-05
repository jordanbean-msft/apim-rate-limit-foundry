"""Offline tests for complete rendered gateway policies and wire-contract safety."""

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
    "web_url": "https://portal.azurewebsites.us",
    "audiences": "<audience>api://client</audience>",
    "subscription_mapping": json.dumps({"subscription-id": "tenant-id"}).replace('"', '\\"'),
    "burst_calls": "60",
    "burst_seconds": "60",
    "send_request_timeout": "10",
    "max_body_bytes": "1048576",
    "max_output_tokens": "4096",
    "max_document_pages": "20",
    "max_language_characters": "5120",
    "model": "sample-model",
    "endpoint": "https://backend.cognitiveservices.azure.us",
    "ai_audience": "https://cognitiveservices.azure.us",
    "api_version": "2024-11-30",
    "price_version": "sample-v1",
    "backend_path": "/model",
    "backend_query": "",
    "llm_policy": "",
}


def render(path: str, **values: str) -> str:
    """Render the templates' scalar substitutions without Azure credentials."""
    variables = PARAMETERS | values
    content = (ROOT / path).read_text()
    return re.sub(r"\$\{([a-z_]+)\}", lambda match: variables[match.group(1)], content)


class GatewayPolicyTests(unittest.TestCase):
    def test_operator_environment_covers_all_deployment_placeholders(self) -> None:
        infra = ROOT.parent / "infra"
        configuration = (infra / "main.tfvars.json").read_text() + (
            infra / "provider.conf.json"
        ).read_text()
        placeholders = set(re.findall(r"\$\{([A-Z_]+)\}", configuration))
        example = json.loads((infra / "environment.example.json").read_text())
        self.assertEqual(placeholders - example.keys(), set())

    def test_complete_rendered_policy_xml(self) -> None:
        for service, prefix in [
            ("foundry", "foundry"),
            ("document-intelligence", "document"),
            ("language", "language"),
        ]:
            with self.subTest(service=service):
                admission = render(f"policies/{prefix}-admission.xml.tftpl")
                settlement = render(
                    "policies/document-submit.xml.tftpl"
                    if prefix == "document"
                    else f"policies/{prefix}-settlement.xml.tftpl"
                )
                xml = render(
                    "policies/ai.xml.tftpl",
                    service=service,
                    admission=admission,
                    settlement=settlement,
                )
                root = ET.fromstring(xml)
                self.assertEqual(root.tag, "policies")
                self.assertEqual(
                    len(root.findall("./inbound/include-fragment[@fragment-id='limiter-reserve']")),
                    1,
                )
                self.assertEqual(
                    root.find("./backend/forward-request").get("buffer-response"), "false"
                )
                self.assertNotIn("/api/decisions/release", xml)
                self.assertNotIn("AsJwt", xml)

    def test_fragments_have_no_policy_sections(self) -> None:
        for name in ["identity", "reserve", "settle"]:
            root = ET.fromstring(render(f"fragments/{name}.xml.tftpl"))
            self.assertEqual(root.tag, "fragment")
            for section in ["inbound", "backend", "outbound", "on-error", "base"]:
                self.assertIsNone(root.find(f".//{section}"))

    def test_identity_validation_precedes_claim_extraction(self) -> None:
        xml = render("fragments/identity.xml.tftpl")
        self.assertLess(xml.index("<validate-jwt"), xml.index('name="principal-id"'))
        self.assertIn('output-token-variable-name="validated-jwt"', xml)
        self.assertNotIn("AsJwt", xml)
        self.assertIn("context.Subscription.Id", xml)
        self.assertNotIn("Subscription.Key", xml)
        self.assertEqual(xml.count("<rate-limit-by-key "), 1)

    def test_streaming_branch_never_reads_response_body(self) -> None:
        xml = render("policies/foundry-settlement.xml.tftpl")
        condition = ET.fromstring(xml).find("when").get("condition")
        self.assertIn('!context.Variables.GetValueOrDefault<bool>("streaming"', condition)
        self.assertIn("preserveContent: true", xml)
        self.assertIn("cached_tokens", xml)

    def test_document_poll_checks_owner_before_backend_and_settles_without_reserving(self) -> None:
        xml = render("policies/document-poll.xml.tftpl")
        ET.fromstring(xml)
        self.assertLess(xml.index("/api/operations/check"), xml.index("<set-backend-service"))
        self.assertIn('"tenant_id"', xml)
        self.assertIn('"principal_id"', xml)
        self.assertNotIn("limiter-reserve", xml)
        self.assertIn("limiter-settle", xml)
        submit = render("policies/document-submit.xml.tftpl")
        ET.fromstring(f"<fragment>{submit}</fragment>")
        self.assertLess(
            submit.index("/api/operations/bind"),
            submit.index('<set-header name="Operation-Location"'),
        )
        admission = render("policies/document-admission.xml.tftpl")
        self.assertIn('body["urlSource"] != null', admission)
        self.assertIn('"^1-([1-9][0-9]?)$"', admission)

    def test_conservative_estimates_and_portal_auth(self) -> None:
        foundry = render("policies/foundry-admission.xml.tftpl")
        self.assertIn('new JProperty("cached_input_tokens", 0)', foundry)
        self.assertIn("UTF8.GetByteCount", foundry)
        self.assertIn('"max_tokens"', foundry)
        language = render("policies/language-admission.xml.tftpl")
        self.assertIn("foreach (var doc in documents) { records +=", language)
        self.assertIn("/ 1000.0", language)
        portal = ET.fromstring(render("policies/portal.xml.tftpl"))
        self.assertIsNotNone(portal.find("./inbound/validate-jwt"))
        self.assertIsNone(portal.find(".//authentication-managed-identity"))


if __name__ == "__main__":
    unittest.main()
