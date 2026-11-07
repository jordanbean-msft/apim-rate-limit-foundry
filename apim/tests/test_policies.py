"""Offline tests for complete rendered gateway policies and wire-contract safety."""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = {
    "service": "foundry",
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
    "max_output_tokens": "4096",
    "max_input_tokens": "200000",
    "context_input_tokens": "200000",
    "max_document_pages": "20",
    "max_language_characters": "5120",
    "llm_tokens_per_minute": "100000",
    "model": "sample-model",
    "endpoint": "https://backend.cognitiveservices.azure.us",
    "ai_audience": "https://cognitiveservices.azure.us",
    "api_version": "2024-11-30",
    "api_protocol": "openai-chat",
    "legacy_default_alias": "sample-model",
    "admission": "",
    "settlement": "",
    "model_lookup": '<include-fragment fragment-id="limiter-model-lookup" />',
    "model_registry": json.dumps(
        {
            "openai-chat:sample-model": {
                "api_protocol": "openai-chat",
                "endpoint": "https://backend.cognitiveservices.azure.us",
                "path": "/openai/deployments/provider-chat/chat/completions",
                "model": "provider-chat",
                "audience": "https://cognitiveservices.azure.us",
                "api_version": "2024-11-30",
                "anthropic_version": "",
                "price_version": "chat-v1",
                "max_input_tokens": 64000,
                "max_output_tokens": 2048,
            },
            "openai-responses:sample-model": {
                "api_protocol": "openai-responses",
                "endpoint": "https://backend.openai.azure.us",
                "path": "/openai/v1/responses",
                "model": "provider-responses",
                "audience": "https://cognitiveservices.azure.us",
                "api_version": "v1",
                "anthropic_version": "",
                "price_version": "responses-v1",
                "max_input_tokens": 64000,
                "max_output_tokens": 1024,
            },
            "anthropic-messages:sample-model": {
                "api_protocol": "anthropic-messages",
                "endpoint": "https://backend.services.ai.azure.com",
                "path": "/anthropic/v1/messages",
                "model": "provider-messages",
                "audience": "https://ai.azure.com",
                "api_version": "",
                "anthropic_version": "2023-06-01",
                "price_version": "messages-v1",
                "max_input_tokens": 128000,
                "max_output_tokens": 1024,
            },
        }
    ).replace('"', '\\"'),
    "price_version": "sample-v1",
    "backend_path": "/model",
    "backend_query": "",
    "llm_policy": "",
    "version_policy": "",
    "provider_headers": "",
}


def render(path: str, **values: str) -> str:
    """Render the templates' scalar substitutions without Azure credentials."""
    variables = PARAMETERS | values
    content = (ROOT / path).read_text()
    return re.sub(r"\$\{([a-z_]+)\}", lambda match: variables[match.group(1)], content)


class GatewayPolicyTests(unittest.TestCase):
    def test_limiter_calls_and_denials_share_gateway_generated_correlation(self) -> None:
        for path in (
            "fragments/reserve.xml.tftpl",
            "fragments/settle.xml.tftpl",
            "policies/document-submit.xml.tftpl",
            "policies/document-poll.xml.tftpl",
        ):
            root = ET.fromstring(
                render(path)
                if "document-submit" not in path
                else "<fragment>" + render(path) + "</fragment>"
            )
            for call in root.findall(".//send-request"):
                header = call.find("./set-header[@name='X-Correlation-ID']/value")
                self.assertIsNotNone(header, path)
                self.assertIn("context.RequestId", header.text)
        reservation = ET.fromstring(render("fragments/reserve.xml.tftpl"))
        denial = next(
            node
            for node in reservation.findall(".//return-response")
            if node.find("./set-status").get("code") == "429"
        )
        self.assertIsNotNone(denial.find("./set-header[@name='X-Correlation-ID']"))
        for path in ("fragments/reserve.xml.tftpl", "fragments/settle.xml.tftpl"):
            root = ET.fromstring(render(path))
            trace = root.find("./trace")
            self.assertIsNotNone(trace)
            metadata = {item.get("name") for item in trace.findall("metadata")}
            self.assertIn("correlation_id", metadata)
            self.assertNotIn("principal_id", metadata)
            self.assertNotIn("request_body", metadata)

    def test_native_llm_denial_precedes_budget_reservation_with_tenant_key(self) -> None:
        native = render("policies/llm-limit.xml.tftpl")
        policy = ET.fromstring(
            render(
                "policies/ai.xml.tftpl",
                service="foundry",
                admission=render("policies/foundry-admission.xml.tftpl"),
                settlement=render("policies/foundry-settlement.xml.tftpl"),
                llm_policy=native,
            )
        )
        statements = list(policy.find("inbound"))
        limiter = policy.find("./inbound/llm-token-limit")
        reservation = policy.find("./inbound/include-fragment[@fragment-id='limiter-reserve']")
        self.assertLess(statements.index(limiter), statements.index(reservation))
        self.assertIn('context.Variables["tenant-id"]', limiter.get("counter-key"))
        self.assertIn('context.Variables["subscription-id"]', limiter.get("counter-key"))
        self.assertNotIn("principal-id", limiter.get("counter-key"))

    def test_unreported_cached_usage_is_not_fabricated_as_zero(self) -> None:
        policy = render("policies/foundry-settlement.xml.tftpl")
        self.assertNotIn('new JProperty("cached_input_tokens",', policy)
        self.assertIn("result[field.Name] = field.Value", policy)
        self.assertIn('"cache_creation"', policy)
        self.assertIn("8192", policy)
        settlement = render("fragments/settle.xml.tftpl")
        self.assertIn('result["data"] as JObject', settlement)
        self.assertIn('(bool?)data["estimated"] != false', settlement)
        self.assertIn('request["provider_usage"]', settlement)
        self.assertIn("} else {", settlement)
        self.assertIn('request["usage"]', settlement)

    def test_operator_environment_covers_all_deployment_placeholders(self) -> None:
        infra = ROOT.parent / "infra"
        configuration = (infra / "main.tfvars.json").read_text() + (
            infra / "provider.conf.json"
        ).read_text()
        placeholders = set(re.findall(r"\$\{([A-Z_]+)\}", configuration))
        example = json.loads((infra / "environment.example.json").read_text())
        self.assertEqual(placeholders - example.keys(), set())
        for filename in ("main.tfvars.json", "provider.conf.json"):
            template = (infra / filename).read_text()
            rendered = re.sub(r"\$\{([A-Z_]+)\}", lambda match: example[match[1]], template)
            parameters = json.loads(rendered)
            if filename == "main.tfvars.json":
                for field in ("llm_models", "managed_models", "applications"):
                    self.assertIsInstance(parameters[field], dict)

    def test_complete_rendered_policy_xml(self) -> None:
        for service, prefix in [
            ("foundry", "foundry"),
            ("foundry", "responses"),
            ("foundry", "anthropic"),
            ("document-intelligence", "document"),
            ("language", "language"),
        ]:
            with self.subTest(service=service):
                admission = render(f"policies/{prefix}-admission.xml.tftpl")
                settlement = render(
                    "policies/document-submit.xml.tftpl"
                    if prefix == "document"
                    else (
                        "policies/foundry-settlement.xml.tftpl"
                        if prefix in {"foundry", "responses", "anthropic"}
                        else f"policies/{prefix}-settlement.xml.tftpl"
                    )
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

    def test_generic_model_lookup_is_exact_and_precedes_admission(self) -> None:
        fragment = ET.fromstring(render("fragments/model-lookup.xml.tftpl"))
        entry = fragment.find("./set-variable[@name='model-entry']")
        self.assertIsNotNone(entry)
        self.assertIn('registry[(string)context.Variables["model-key"]]', entry.get("value"))
        self.assertIn('context.Variables["api-protocol"]', entry.get("value"))
        self.assertIn("return entry.ToString", entry.get("value"))
        self.assertEqual(len(fragment.findall(".//when")), 1)
        self.assertIn(
            "limiter-model-lookup", render("policies/ai.xml.tftpl").split("${admission}")[0]
        )
        template = (ROOT / "policies/ai.xml.tftpl").read_text()
        self.assertLess(template.index("${model_lookup}"), template.index("${admission}"))

    def test_service_routes_keep_model_and_price_before_reservation(self) -> None:
        for service, model in (
            ("document-intelligence", "prebuilt-read"),
            ("language", "sentiment"),
        ):
            with self.subTest(service=service):
                root = ET.fromstring(
                    render(
                        "policies/ai.xml.tftpl",
                        service=service,
                        api_protocol="",
                        model=model,
                        price_version="service-v1",
                        model_lookup="",
                    )
                )
                inbound = root.find("inbound")
                statements = list(inbound)
                reserve = inbound.find("./include-fragment[@fragment-id='limiter-reserve']")
                for name, value in (("model", model), ("price-version", "service-v1")):
                    variable = inbound.find(f"./set-variable[@name='{name}']")
                    self.assertIsNotNone(variable)
                    self.assertEqual(variable.get("value"), value)
                    self.assertLess(statements.index(variable), statements.index(reserve))

    def test_provider_deployment_rewrite_precedes_stream_hash_and_reservation(self) -> None:
        policy = render("policies/ai.xml.tftpl")
        inbound = policy.split("<inbound>", 1)[1].split("</inbound>", 1)[0]
        self.assertLess(
            inbound.index('body["model"] = (string)context.Variables["model-provider"]'),
            inbound.index('name="payload-sha256"'),
        )
        self.assertLess(
            inbound.index('name="payload-sha256"'), inbound.index('fragment-id="limiter-reserve"')
        )
        template = (ROOT / "policies/ai.xml.tftpl").read_text()
        self.assertLess(template.index("${model_lookup}"), template.index("${admission}"))
        self.assertIn('context.Variables["model-endpoint"]', inbound)
        self.assertIn('context.Variables["model-path"]', inbound)
        self.assertIn('context.Variables["model-audience"]', inbound)
        self.assertIn('context.Variables["price-version"]', render("fragments/reserve.xml.tftpl"))

    def test_model_admission_uses_selected_registry_token_limits(self) -> None:
        for path in (
            "policies/foundry-admission.xml.tftpl",
            "policies/responses-admission.xml.tftpl",
            "policies/anthropic-admission.xml.tftpl",
        ):
            content = render(path)
            self.assertIn('context.Variables["model-max-output-tokens"]', content)
            if "anthropic" in path:
                self.assertIn('context.Variables["model-max-input-tokens"]', content)
            else:
                self.assertIn('context.Variables["model-max-input-tokens"]', content)

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

    def test_every_gateway_requires_both_jwt_and_native_product_subscription(self) -> None:
        for path, inbound_path in (
            ("fragments/identity.xml.tftpl", "."),
            ("policies/portal.xml.tftpl", "./inbound"),
        ):
            with self.subTest(path=path):
                root = ET.fromstring(render(path))
                inbound = root.find(inbound_path)
                jwt = inbound.find("./validate-jwt")
                self.assertIsNotNone(jwt)
                self.assertEqual(jwt.get("header-name"), "Authorization")
                guard = inbound.find("./choose/when")
                self.assertIn("context.Subscription == null", guard.get("condition"))
                self.assertIn("context.Product == null", guard.get("condition"))
                self.assertIn("Ocp-Apim-Subscription-Key", guard.get("condition"))
                self.assertEqual(guard.find("./return-response/set-status").get("code"), "401")
                self.assertIsNotNone(
                    inbound.find("./set-query-parameter[@name='subscription-key']")
                )
                self.assertLess(
                    list(inbound).index(inbound.find("./choose")), list(inbound).index(jwt)
                )
                self.assertNotIn("subscription_mapping", render(path))
        reservation = render("fragments/reserve.xml.tftpl")
        self.assertIn(
            'new JProperty("subscription_id", (string)context.Variables["subscription-id"])',
            reservation,
        )
        self.assertNotIn("context.Subscription == null ? null", reservation)

    def test_native_burst_denials_attribute_subscriptions_without_key_or_user_data(self) -> None:
        xml = render("fragments/identity.xml.tftpl")
        fragment = ET.fromstring(xml)
        digest = fragment.find("./set-variable[@name='caller-ref']").get("value")
        self.assertIn(
            '(string)context.Variables["tenant-id"] + "\\n" + (string)context.Variables["subscription-id"]',
            digest,
        )
        self.assertIn(
            "SHA256.Create().ComputeHash(System.Text.Encoding.UTF8.GetBytes(identity))", digest
        )
        self.assertIn('Replace("-", "").ToLowerInvariant()', digest)
        trace = fragment.find("./trace")
        self.assertEqual(trace.find("message").text, "gateway_caller")
        metadata = {item.get("name") for item in trace.findall("metadata")}
        self.assertEqual(
            metadata,
            {
                "correlation_id",
                "caller_ref",
                "subscription_id",
                "application_name",
                "product_id",
                "api_id",
                "operation_id",
            },
        )
        self.assertNotIn('Variables["tenant-id"]', ET.tostring(trace, encoding="unicode"))
        self.assertNotIn('Variables["principal-id"]', ET.tostring(trace, encoding="unicode"))
        burst_key = fragment.find("./rate-limit-by-key").get("counter-key")
        self.assertIn('Variables["subscription-id"]', burst_key)
        self.assertNotIn("principal-id", burst_key)
        for secret_property in (
            "Subscription.Key",
            "Subscription.PrimaryKey",
            "Subscription.SecondaryKey",
        ):
            self.assertNotIn(secret_property, xml)
        self.assertLess(xml.index('name="caller-ref"'), xml.index("<trace"))
        self.assertLess(xml.index("<trace"), xml.index("<rate-limit-by-key"))
        self.assertLess(xml.index("<validate-jwt"), xml.index("<trace"))

    def test_streaming_branch_never_reads_response_body(self) -> None:
        xml = render("policies/foundry-settlement.xml.tftpl")
        condition = ET.fromstring(xml).find("when").get("condition")
        self.assertIn('!context.Variables.GetValueOrDefault<bool>("streaming"', condition)
        self.assertIn('StartsWith("application/json")', condition)
        self.assertIn("preserveContent: true", xml)
        self.assertIn("prompt_tokens_details", xml)
        self.assertIn("input_tokens_details", xml)

    def test_raw_provider_usage_only_is_forwarded_without_response_contents(self) -> None:
        policy = ET.fromstring(render("policies/foundry-settlement.xml.tftpl"))
        expression = policy.find("./when/set-variable").get("value")
        self.assertIn('var usage = body["usage"] as JObject', expression)
        self.assertIn("var result = new JObject()", expression)
        self.assertNotIn("return body.ToString()", expression)
        self.assertIn("field.Value.Type != JTokenType.Integer", expression)
        self.assertNotIn('new JProperty("input_tokens",', expression)
        fragment = render("fragments/settle.xml.tftpl")
        self.assertNotIn('request["api_protocol"]', fragment)
        reserve = render("fragments/reserve.xml.tftpl")
        self.assertIn('request["api_protocol"]', reserve)
        self.assertIn('if (!permitted.Contains(field.Name)) { return ""; }', expression)
        for field in ["service_tier", "inference_geo", "server_tool_use"]:
            self.assertIn(f'"{field}"', expression)
        for protocol in ["foundry", "responses", "anthropic"]:
            admission = render(f"policies/{protocol}-admission.xml.tftpl")
            fields = admission.split("foreach (var field in body.Properties())", 1)[0]
            for override in ["service_tier", "inference_geo", "speed", "batch"]:
                self.assertNotIn(f'"{override}"', fields)

    def test_anthropic_uses_verified_full_context_not_openai_byte_estimation(self) -> None:
        policy = ET.fromstring(
            "<fragment>" + render("policies/anthropic-admission.xml.tftpl") + "</fragment>"
        )
        usage = policy.find("./set-variable[@name='usage']").get("value")
        self.assertIn(
            'new JProperty("input_tokens", (int)context.Variables["model-max-input-tokens"])', usage
        )
        self.assertNotIn("UTF8", usage)
        validation = policy.find("./set-variable[@name='admission-error']").get("value")
        self.assertIn('"cache_control"', validation)
        self.assertIn('"5m","1h"', validation)
        self.assertIn('"tool_use"', validation)
        self.assertIn('"tool_result"', validation)
        self.assertIn("only inline client tool definitions", validation)

    def test_usage_null_guard_only_allows_known_optional_objects(self) -> None:
        policy = ET.fromstring(render("policies/foundry-settlement.xml.tftpl"))
        expression = policy.find("./when/set-variable").get("value")
        nullable = re.search(r"var nullableObjects = new \[\] \{([^}]+)};", expression)
        allowed = set(re.findall(r'"([^"]+)"', nullable[1]))
        anthropic_usage = {
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_creation": None,
            "server_tool_use": None,
        }
        openai_usage = {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "prompt_tokens_details": None,
            "completion_tokens_details": None,
            "input_tokens_details": None,
            "output_tokens_details": None,
        }
        for usage in [anthropic_usage, openai_usage]:
            with self.subTest(usage=usage):
                null_fields = {key for key, value in usage.items() if value is None}
                self.assertLessEqual(null_fields, allowed)
        self.assertFalse({"input_tokens", "output_tokens", "unknown_detail"} & allowed)
        self.assertRegex(
            expression,
            r"if \(field.Value.Type == JTokenType.Null\) \{\s+"
            r'if \(!nullableObjects.Contains\(field.Name\)\) \{ return ""; }',
        )
        self.assertLess(
            expression.index("!permitted.Contains(field.Name)"),
            expression.index("field.Value.Type == JTokenType.Null"),
        )
        self.assertIn("result[field.Name] = field.Value", expression)
        self.assertNotIn("JTokenType.Null ? 0", expression)

    def test_responses_native_output_roundtrip_metadata_stays_inline(self) -> None:
        policy = ET.fromstring(
            "<fragment>" + render("policies/responses-admission.xml.tftpl") + "</fragment>"
        )
        expression = policy.find("./set-variable[@name='admission-error']").get("value")
        message = {
            "type": "message",
            "id": "msg_example",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Done", "annotations": [], "logprobs": []}],
        }
        call = {
            "type": "function_call",
            "id": "fc_example",
            "status": "completed",
            "name": "lookup",
            "call_id": "call_example",
            "arguments": '{"key":"value"}',
        }
        for branch, fixture in [
            ('if (type == "message")', message),
            ('else if (type == "function_call")', call),
        ]:
            with self.subTest(item=fixture["type"]):
                branch_expression = expression.split(branch, 1)[1]
                fields = re.search(
                    r"new \[\] \{([^}]+)}\.Contains\(field.Name\)", branch_expression
                )
                self.assertLessEqual(fixture.keys(), set(re.findall(r'"([^"]+)"', fields[1])))
        self.assertIn('((string)item["id"]).Length > 200', expression)
        self.assertIn('String.IsNullOrEmpty((string)item["id"])', expression)
        self.assertIn('(string)item["status"] != "completed"', expression)
        self.assertIn('if (content == null) { return "message content is required"; }', expression)
        self.assertIn('item["arguments"] == null', expression)
        self.assertIn('"type","text","annotations","logprobs"', expression)
        self.assertIn('((JArray)block["logprobs"]).Count != 0', expression)
        self.assertIn('(string)block["type"] != "output_text"', expression)
        self.assertNotIn('"item_reference"', expression)
        self.assertNotIn('"previous_response_id"', expression)
        self.assertNotIn('"encrypted_content"', expression)
        self.assertIn(
            'return "opaque history and provider-managed items are unsupported"', expression
        )
        self.assertIn("body.ToString()", policy.find("./set-body").text)

    def test_openai_protocols_validate_bounds_and_preserve_supported_fields(self) -> None:
        chat = render("policies/foundry-admission.xml.tftpl")
        self.assertIn("supply exactly one output-token cap", chat)
        self.assertIn('body["max_tokens"] ?? body["max_completion_tokens"]', chat)
        self.assertIn("n must be 1", chat)
        self.assertIn('"tool_calls"', chat)
        self.assertIn('"tool_call_id"', chat)
        self.assertIn("UTF8.GetByteCount(body.ToString())", chat)
        responses = render("policies/responses-admission.xml.tftpl")
        self.assertIn('"function_call_output"', responses)
        self.assertIn('"max_output_tokens"', responses)
        self.assertIn('body["store"] = false', responses)
        self.assertIn('body["background"] = false', responses)
        self.assertNotIn('"previous_response_id"', responses)
        self.assertIn("unsupported Responses field:", responses)
        for protocol in ["foundry", "responses", "anthropic"]:
            admission = ET.fromstring(
                "<fragment>" + render(f"policies/{protocol}-admission.xml.tftpl") + "</fragment>"
            )
            for body in admission.findall("set-body"):
                self.assertIn("body.ToString()", body.text)
                self.assertNotIn("new JObject(", body.text)

    def test_provider_credentials_are_stripped_and_anthropic_version_is_pinned(self) -> None:
        policy = ET.fromstring(
            render(
                "policies/ai.xml.tftpl",
                service="foundry",
                api_protocol="anthropic-messages",
                admission=render("policies/anthropic-admission.xml.tftpl"),
                settlement=render("policies/foundry-settlement.xml.tftpl"),
                provider_headers='<set-header name="anthropic-version" exists-action="override"><value>2023-06-01</value></set-header>',
            )
        )
        for name in [
            "api-key",
            "x-api-key",
            "api-version",
            "anthropic-beta",
            "OpenAI-Beta",
            "OpenAI-Organization",
            "OpenAI-Project",
        ]:
            self.assertEqual(
                policy.find(f"./inbound/set-header[@name='{name}']").get("exists-action"), "delete"
            )
        self.assertEqual(
            policy.find(".//otherwise/set-header[@name='anthropic-version']/value").text,
            "2023-06-01",
        )
        for rewrite in policy.findall(".//rewrite-uri"):
            self.assertEqual(rewrite.get("copy-unmatched-params"), "false")
        self.assertIsNone(policy.find("./inbound/set-query-parameter[@name='api-version']"))

    def test_stream_body_is_pinned_before_hash_and_reservation(self) -> None:
        xml = render(
            "policies/ai.xml.tftpl",
            admission=render("policies/foundry-admission.xml.tftpl"),
            settlement=render("policies/foundry-settlement.xml.tftpl"),
        )
        policy = ET.fromstring(xml)
        digest = policy.find(".//set-variable[@name='payload-sha256']").get("value")
        self.assertIn("Encoding.UTF8.GetBytes", digest)
        self.assertIn("SHA256.Create().ComputeHash(bytes)", digest)
        self.assertIn('Replace("-", "").ToLowerInvariant()', digest)
        self.assertLess(xml.index('body["model"] ='), xml.index('name="payload-sha256"'))
        self.assertLess(xml.index('new JProperty("include_usage", true)'), xml.index("ComputeHash"))
        self.assertLess(xml.index("ComputeHash"), xml.index('fragment-id="limiter-reserve"'))
        self.assertLess(
            xml.index('fragment-id="limiter-reserve"'), xml.index("<set-backend-service")
        )
        reserve = ET.fromstring(render("fragments/reserve.xml.tftpl"))
        body = reserve.find(".//set-body").text
        self.assertIn('GetValueOrDefault<bool>("streaming", false)', body)
        self.assertIn(
            'request["payload_sha256"] = (string)context.Variables["payload-sha256"]', body
        )

    def test_stream_relay_uses_api_identity_and_never_provider_credentials(self) -> None:
        policy = ET.fromstring(
            render(
                "policies/ai.xml.tftpl",
                admission=render("policies/foundry-admission.xml.tftpl"),
                settlement=render("policies/foundry-settlement.xml.tftpl"),
                version_policy='<set-query-parameter name="api-version" exists-action="override"><value>v1</value></set-query-parameter>',
            )
        )
        relay = next(
            branch
            for branch in policy.findall("./inbound/choose/when")
            if branch.find("./rewrite-uri[@template='/api/stream']") is not None
        )
        self.assertIn("true &&", relay.get("condition"))
        self.assertEqual(
            relay.find("set-backend-service").get("base-url"), PARAMETERS["stream_url"]
        )
        self.assertEqual(
            relay.find("authentication-managed-identity").get("resource"),
            PARAMETERS["api_audience"],
        )
        self.assertEqual(
            relay.find("authentication-managed-identity").get("client-id"),
            PARAMETERS["gateway_client_id"],
        )
        self.assertEqual(relay.find("set-query-parameter").get("exists-action"), "delete")
        self.assertEqual(
            relay.find("./set-header[@name='X-RateLimit-Reservation']").get("exists-action"),
            "override",
        )
        self.assertIn(
            "context.RequestId", relay.find("./set-header[@name='X-Correlation-ID']/value").text
        )
        for name in ("Authorization", "api-key", "x-api-key", "X-RateLimit-Reservation"):
            self.assertEqual(
                policy.find(f"./inbound/set-header[@name='{name}']").get("exists-action"), "delete"
            )
        direct = policy.find(
            ".//set-backend-service[@base-url='@((string)context.Variables[\"model-endpoint\"])']"
        )
        self.assertIsNotNone(direct)
        identities = policy.findall(".//authentication-managed-identity")
        self.assertIn(
            '@((string)context.Variables["model-audience"])',
            [identity.get("resource") for identity in identities],
        )
        self.assertEqual(policy.find("./backend/forward-request").get("buffer-response"), "false")
        outbound = policy.find("outbound")
        self.assertEqual(
            outbound.find("./set-header[@name='X-RateLimit-Estimated']/value").text, "true"
        )
        self.assertEqual(
            outbound.find(".//set-header[@name='X-RateLimit-Admission']/value").text,
            "conservative",
        )
        self.assertEqual(
            outbound.find(".//set-header[@name='X-RateLimit-Accounting']/value").text,
            "provider-stream",
        )

    def test_chat_stream_options_accept_only_boolean_usage_and_force_true(self) -> None:
        policy = ET.fromstring(
            "<fragment>" + render("policies/foundry-admission.xml.tftpl") + "</fragment>"
        )
        admission = policy.find("./set-variable[@name='admission-error']").get("value")
        self.assertIn('"stream_options"', admission)
        self.assertIn('field.Name != "include_usage"', admission)
        self.assertIn('options["include_usage"].Type != JTokenType.Boolean', admission)
        self.assertIn("options == null", admission)
        xml = render("policies/ai.xml.tftpl", admission="", settlement="")
        self.assertIn(
            'body["stream_options"] = new JObject(new JProperty("include_usage", true))', xml
        )

    def test_document_poll_checks_owner_before_backend_and_settles_without_reserving(self) -> None:
        xml = render("policies/document-poll.xml.tftpl")
        ET.fromstring(xml)
        self.assertLess(xml.index("/api/operations/check"), xml.index("<set-backend-service"))
        self.assertIn('"tenant_id"', xml)
        self.assertIn('"principal_id"', xml)
        self.assertIn('"subscription_id"', xml)
        self.assertNotIn("limiter-reserve", xml)
        self.assertIn("limiter-settle", xml)
        submit = render("policies/document-submit.xml.tftpl")
        ET.fromstring(f"<fragment>{submit}</fragment>")
        self.assertIn('"subscription_id"', submit)
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
