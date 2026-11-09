import base64
import binascii
import json
from dataclasses import dataclass

from fastapi import HTTPException, Request

from apim_rate_limit_foundry.config import Settings


@dataclass(frozen=True)
class Identity:
    tenant_id: str
    principal_id: str
    roles: frozenset[str]

    def require(self, *roles: str) -> None:
        if not self.roles.intersection(roles):
            raise HTTPException(403, "Role not authorized")


def authenticate(request: Request, settings: Settings) -> Identity:
    if settings.local_auth_enabled and not settings.in_azure:
        tenant = request.headers.get("x-local-tenant-id", "")
        principal = request.headers.get("x-local-principal-id", "")
        roles = frozenset(request.headers.get("x-local-roles", "").split(","))
    elif settings.in_azure and settings.website_auth_enabled:
        encoded = request.headers.get("x-ms-client-principal", "")
        try:
            if len(encoded) > 65536:
                raise ValueError("Principal too large")
            parsed = json.loads(base64.b64decode(encoded, validate=True))
            if not isinstance(parsed, dict) or parsed.get("auth_typ") != "aad":
                raise ValueError("Unsupported identity provider")
            claims = parsed["claims"]
            if not isinstance(claims, list):
                raise ValueError("Invalid claims")
            values: dict[str, list[str]] = {}
            for claim in claims:
                if (
                    not isinstance(claim, dict)
                    or not isinstance(claim.get("typ"), str)
                    or not isinstance(claim.get("val"), str)
                ):
                    raise ValueError("Invalid claim")
                values.setdefault(claim["typ"], []).append(claim["val"])
            tenant_values = values.get(
                "tid", values.get("http://schemas.microsoft.com/identity/claims/tenantid", [])
            )
            principal_values = values.get(
                "oid",
                values.get("http://schemas.microsoft.com/identity/claims/objectidentifier", []),
            )
            if len(tenant_values) != 1 or len(principal_values) != 1:
                raise ValueError("Ambiguous principal")
            tenant, principal = tenant_values[0], principal_values[0]
            roles = frozenset(
                values.get("roles", [])
                + values.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role", [])
            )
            if "RateLimit.Gateway" in roles:
                client_ids = {
                    value.casefold()
                    for claim_type in ("azp", "appid")
                    for value in values.get(claim_type, [])
                }
                if not settings.gateway_client_id or client_ids != {
                    settings.gateway_client_id.casefold()
                }:
                    raise ValueError("Unexpected gateway client")
        except (ValueError, KeyError, TypeError, binascii.Error) as error:
            raise HTTPException(401, "Invalid platform principal") from error
    else:
        raise HTTPException(401, "Authentication is not configured")
    if (
        not tenant
        or not principal
        or (settings.azure_tenant_id and tenant != settings.azure_tenant_id)
    ):
        raise HTTPException(401, "Invalid tenant or principal")
    return Identity(tenant, principal, roles)
