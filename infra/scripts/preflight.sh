#!/bin/sh
set -eu

for name in AZURE_CLOUD ARM_ENVIRONMENT AZURE_SUBSCRIPTION_ID AZURE_TENANT_ID AZURE_LOCATION AZURE_RESOURCE_GROUP AZURE_PRINCIPAL_ID PUBLIC_NETWORK_ACCESS_ENABLED RS_RESOURCE_GROUP RS_STORAGE_ACCOUNT RS_CONTAINER_NAME GATEWAY_CLIENT_AUDIENCE APIM_PUBLISHER_NAME APIM_PUBLISHER_EMAIL REDIS_TOKEN_SCOPE MAX_INPUT_TOKENS OPENAI_BYTE_TOKENIZER_VERIFIED LLM_MODELS MANAGED_MODELS APPLICATION_SUBSCRIPTIONS_CONFIG EVENT_HUB_CAPACITY EVENT_HUB_PARTITIONS EVENT_HUB_RETENTION_DAYS; do
  value=$(printenv "$name" || true)
  [ -n "$value" ] || { echo "Missing required azd environment value: $name" >&2; exit 1; }
done

case "$AZURE_CLOUD:$ARM_ENVIRONMENT" in
  AzureCloud:public) ;;
  AzureUSGovernment:usgovernment) ;;
  *) echo "AZURE_CLOUD and ARM_ENVIRONMENT disagree; no cloud fallback is allowed." >&2; exit 1 ;;
esac
[ "$(az cloud show --query name -o tsv)" = "$AZURE_CLOUD" ] || {
  echo "Select the matching Azure CLI and azd cloud before provisioning." >&2; exit 1;
}
[ "$(az account show --query tenantId -o tsv)" = "$AZURE_TENANT_ID" ] || {
  echo "Azure CLI tenant does not match AZURE_TENANT_ID." >&2; exit 1;
}
az group show --subscription "$AZURE_SUBSCRIPTION_ID" --name "$AZURE_RESOURCE_GROUP" --output none

case "$PUBLIC_NETWORK_ACCESS_ENABLED" in
  false)
    for name in PRIVATE_ENDPOINT_SUBNET_ID FUNCTIONS_SUBNET_ID WEB_SUBNET_ID APIM_SUBNET_ID; do
      value=$(printenv "$name" || true)
      case "$value" in /subscriptions/*/subnets/*) ;; *) echo "Missing pre-created subnet: $name" >&2; exit 1 ;; esac
      az network vnet subnet show --ids "$value" --output none
    done
    echo "Private deployment: runner must reach private SCM, Storage/Table and DNS; APIM subnet requires documented outbound/management routes."
    ;;
  true) echo "WARNING: explicit public-network development mode enabled." >&2 ;;
  *) echo "PUBLIC_NETWORK_ACCESS_ENABLED must be explicitly true or false." >&2; exit 1 ;;
esac

for service in FOUNDRY; do
  enabled=$(printenv "ENABLE_$service" || true)
  create=$(printenv "CREATE_$service" || true)
  case "$enabled:$create" in true:true|true:false|false:true|false:false) ;; *) echo "Set ENABLE_$service and CREATE_$service explicitly." >&2; exit 1 ;; esac
  if [ "$enabled:$create" = "true:false" ]; then
    endpoint=$(printenv "${service}_ENDPOINT" || true)
    resource=$(printenv "${service}_RESOURCE_ID" || true)
    case "$service:$AZURE_CLOUD:$endpoint" in
      *:AzureCloud:https://*.openai.azure.com|*:AzureCloud:https://*.cognitiveservices.azure.com) ;;
      *:AzureUSGovernment:https://*.openai.azure.us|*:AzureUSGovernment:https://*.cognitiveservices.azure.us) ;;
      FOUNDRY:AzureCloud:https://*.services.ai.azure.com|FOUNDRY:AzureUSGovernment:https://*.services.ai.azure.us) ;;
      *) echo "$service requires an exact custom-subdomain endpoint in the selected cloud (no path/trailing slash)." >&2; exit 1 ;;
    esac
    az resource show --ids "$resource" --output none
    [ "$(az resource show --ids "$resource" --query properties.disableLocalAuth -o tsv)" = "true" ] || {
      echo "$service reference must disable local/key authentication; only APIM should hold data-plane RBAC." >&2; exit 1;
    }
  fi
  if [ "$enabled" = "true" ]; then
    audience=$(printenv "${service}_TOKEN_AUDIENCE" || true)
    case "$audience" in https://cognitiveservices.azure.com|https://cognitiveservices.azure.us) ;; *) echo "Explicit verified ${service}_TOKEN_AUDIENCE is required; do not infer it from DNS." >&2; exit 1 ;; esac
  fi
done
for protocol in RESPONSES; do
  enabled=$(printenv "ENABLE_$protocol" || true)
  case "$enabled" in true|false) ;; *) echo "Set ENABLE_$protocol explicitly." >&2; exit 1 ;; esac
  [ "$enabled" = "true" ] || continue
  [ "$(printenv "${protocol}_CAPABILITY_VERIFIED" || true)" = "true" ] || {
    echo "$protocol requires documented endpoint/model/region/audience capability verification." >&2; exit 1;
  }
  for field in RESOURCE_ID ENDPOINT TOKEN_AUDIENCE LOCATION DEPLOYMENT_NAME PRICE_VERSION ROLE_NAME; do
    [ -n "$(printenv "${protocol}_$field" || true)" ] || {
      echo "Missing required enabled-protocol setting: ${protocol}_$field" >&2; exit 1;
    }
  done
  endpoint=$(printenv "${protocol}_ENDPOINT" || true)
  resource=$(printenv "${protocol}_RESOURCE_ID" || true)
  case "$protocol:$AZURE_CLOUD:$endpoint" in
    RESPONSES:AzureCloud:https://*.openai.azure.com) ;;
    RESPONSES:AzureUSGovernment:https://*.openai.azure.us)
      [ "$(printenv RESPONSES_GOVERNMENT_VERIFIED || true)" = "true" ] || {
        echo "Revalidate Responses Government availability before enabling it." >&2; exit 1;
      } ;;
    *) echo "$protocol endpoint is not verified for the selected cloud; no cross-cloud fallback." >&2; exit 1 ;;
  esac
  az resource show --ids "$resource" --output none
  [ "$(az resource show --ids "$resource" --query properties.disableLocalAuth -o tsv)" = "true" ] || {
    echo "$protocol must disable backend key authentication." >&2; exit 1;
  }
  if [ "$PUBLIC_NETWORK_ACCESS_ENABLED" = "false" ]; then
    [ "$(printenv "${protocol}_PRIVATE_ENDPOINT_VERIFIED" || true)" = "true" ] || {
      echo "$protocol referenced endpoint requires verified private DNS/routing." >&2; exit 1;
    }
    [ "$(az resource show --ids "$resource" --query properties.publicNetworkAccess -o tsv)" = "Disabled" ] || {
      echo "$protocol must be private-only in private deployment mode." >&2; exit 1;
    }
  fi
  [ "$(printenv RESPONSES_BYTE_TOKENIZER_VERIFIED || true)" = "true" ] || {
    echo "Responses native token-limit compatibility must be explicitly verified." >&2; exit 1;
  }
done
model_references=$(uv run --no-sync python -c '
import json
import re
import sys
from urllib.parse import urlsplit

try:
    models = json.loads(sys.argv[1])
except (json.JSONDecodeError, TypeError):
    raise SystemExit("LLM_MODELS must be a JSON object")
if not isinstance(models, dict):
    raise SystemExit("LLM_MODELS must be a JSON object")
cloud = sys.argv[2]
private = sys.argv[3] == "false"
try:
    function_max_input = int(sys.argv[4])
except ValueError:
    raise SystemExit("MAX_INPUT_TOKENS must be a positive integer")
if function_max_input < 1:
    raise SystemExit("MAX_INPUT_TOKENS must be a positive integer")
roles = {"Cognitive Services User", "Cognitive Services OpenAI User", "Azure AI User", "Foundry User"}
for key, model in sorted(models.items()):
    if not isinstance(model, dict):
        raise SystemExit(f"{key}: model entry must be an object")
    parts = key.split(":")
    if len(parts) != 2 or parts[0] not in {"openai-chat", "openai-responses"} or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", parts[1]) is None:
        raise SystemExit(f"{key}: expected a safe protocol:alias key")
    protocol = parts[0]
    required = ("api_protocol", "resource_id", "endpoint", "audience", "location", "deployment_name", "price_version", "max_input_tokens", "max_output_tokens", "role_definition_name", "capability_verified", "government_verified", "byte_tokenizer_verified", "private_endpoint_verified", "api_version")
    if any(field not in model for field in required) or model["api_protocol"] != protocol:
        raise SystemExit(f"{key}: missing required fields or api_protocol does not match the key")
    if not isinstance(model["resource_id"], str) or not model["resource_id"].startswith("/subscriptions/"):
        raise SystemExit(f"{key}: resource_id must identify an Azure resource")
    if not isinstance(model["deployment_name"], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model["deployment_name"]) is None:
        raise SystemExit(f"{key}: invalid provider deployment name")
    if not isinstance(model["price_version"], str) or re.fullmatch(r"[A-Za-z0-9._-]{1,200}", model["price_version"]) is None:
        raise SystemExit(f"{key}: invalid price version")
    for field, maximum in (("max_input_tokens", function_max_input), ("max_output_tokens", 999999)):
        value = model[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
            raise SystemExit(f"{key}: {field} must be a positive integer within the global cap")
    if model["role_definition_name"] not in roles:
        raise SystemExit(f"{key}: unsupported least-privilege role")
    if private and model["private_endpoint_verified"] is not True:
        raise SystemExit(f"{key}: private endpoint and DNS verification is required")
    endpoint = urlsplit(model["endpoint"] if isinstance(model["endpoint"], str) else "")
    audience = urlsplit(model["audience"] if isinstance(model["audience"], str) else "")
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment:
        raise SystemExit(f"{key}: endpoint must be an HTTPS origin without credentials, path, query, or fragment")
    if audience.scheme != "https" or not audience.hostname or audience.username or audience.password or audience.path not in ("", "/") or audience.query or audience.fragment:
        raise SystemExit(f"{key}: audience must be an HTTPS origin")
    host = endpoint.hostname.lower()
    if cloud == "AzureUSGovernment":
        allowed = host.endswith((".openai.azure.us", ".cognitiveservices.azure.us", ".services.ai.azure.us"))
        if not allowed or audience.geturl().rstrip("/").lower() != "https://cognitiveservices.azure.us":
            raise SystemExit(f"{key}: endpoint and Cognitive Services audience must be Government resources")
    else:
        allowed = host.endswith((".openai.azure.com", ".cognitiveservices.azure.com", ".services.ai.azure.com"))
        if not allowed or audience.geturl().rstrip("/").lower() not in {"https://ai.azure.com", "https://cognitiveservices.azure.com"}:
            raise SystemExit(f"{key}: endpoint and audience must be supported Commercial origins")
    if model["capability_verified"] is not True:
        raise SystemExit(f"{key}: capability verification is required")
    if model["byte_tokenizer_verified"] is not True:
        raise SystemExit(f"{key}: native token-limit verification is required")
    if protocol == "openai-responses":
        if model["api_version"] not in {"v1", "preview"} or (cloud == "AzureUSGovernment" and model["government_verified"] is not True):
            raise SystemExit(f"{key}: Responses version and sovereign capability must be verified")
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}(-preview)?", model["api_version"]) is None:
        raise SystemExit(f"{key}: Chat API version is required")
    print("\t".join((model["resource_id"], protocol, str(model["private_endpoint_verified"]).lower())))
' "$LLM_MODELS" "$AZURE_CLOUD" "$PUBLIC_NETWORK_ACCESS_ENABLED" "$MAX_INPUT_TOKENS") || {
  echo "Invalid LLM_MODELS configuration." >&2; exit 1;
}
printf '%s\n' "$model_references" | while IFS="$(printf '\t')" read -r resource protocol private_verified; do
  [ -n "$resource" ] || continue
  az resource show --ids "$resource" --output none
  [ "$(az resource show --ids "$resource" --query properties.disableLocalAuth -o tsv)" = "true" ] || {
    echo "$protocol referenced model must disable backend key authentication." >&2; exit 1;
  }
  if [ "$PUBLIC_NETWORK_ACCESS_ENABLED" = "false" ]; then
    [ "$private_verified" = "true" ] || {
      echo "$protocol referenced model requires verified private DNS/routing." >&2; exit 1;
    }
    [ "$(az resource show --ids "$resource" --query properties.publicNetworkAccess -o tsv)" = "Disabled" ] || {
      echo "$protocol referenced model must be private-only in private deployment mode." >&2; exit 1;
    }
  fi
done
echo "Preflight passed. Confirm regional model quota, AI API versions, Redis SKU, DINE private DNS, and Graph application permissions before provision."
