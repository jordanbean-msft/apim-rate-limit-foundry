#!/bin/sh
set -eu

for name in AZURE_CLOUD ARM_ENVIRONMENT AZURE_SUBSCRIPTION_ID AZURE_TENANT_ID AZURE_LOCATION AZURE_RESOURCE_GROUP AZURE_PRINCIPAL_ID PUBLIC_NETWORK_ACCESS_ENABLED RS_RESOURCE_GROUP RS_STORAGE_ACCOUNT RS_CONTAINER_NAME GATEWAY_CLIENT_AUDIENCE APIM_PUBLISHER_NAME APIM_PUBLISHER_EMAIL REDIS_TOKEN_SCOPE; do
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

for service in FOUNDRY DOCUMENT_INTELLIGENCE LANGUAGE; do
  enabled=$(printenv "ENABLE_$service" || true)
  create=$(printenv "CREATE_$service" || true)
  case "$enabled:$create" in true:true|true:false|false:true|false:false) ;; *) echo "Set ENABLE_$service and CREATE_$service explicitly." >&2; exit 1 ;; esac
  if [ "$enabled:$create" = "true:false" ]; then
    endpoint=$(printenv "${service}_ENDPOINT" || true)
    resource=$(printenv "${service}_RESOURCE_ID" || true)
    case "$AZURE_CLOUD:$endpoint" in
      AzureCloud:https://*.openai.azure.com|AzureCloud:https://*.cognitiveservices.azure.com) ;;
      AzureUSGovernment:https://*.openai.azure.us|AzureUSGovernment:https://*.cognitiveservices.azure.us) ;;
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
echo "Preflight passed. Confirm regional model quota, AI API versions, Redis SKU, DINE private DNS, and Graph application permissions before provision."
