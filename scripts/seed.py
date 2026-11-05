"""Seed explicit sample records through the authenticated administration API."""

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class SeedSettings(BaseSettings):
    seed_api_url: str = "http://127.0.0.1:8000/api"
    seed_access_token: str = ""
    seed_local_auth: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Save sample policies/prices (without this flag, print the records only)",
    )
    args = parser.parse_args()
    settings = SeedSettings()
    parsed = urlsplit(settings.seed_api_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("Use HTTPS, except for an explicit loopback development endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The API URL cannot contain credentials, a query, or a fragment")
    if parsed.scheme == "https" and not settings.seed_access_token:
        raise ValueError("SEED_ACCESS_TOKEN is required for a deployed endpoint")
    headers = (
        {"Authorization": f"Bearer {settings.seed_access_token}"}
        if settings.seed_access_token
        else {}
    )
    if settings.seed_local_auth:
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Local seed identity headers are permitted only on loopback HTTP")
        headers = {
            "X-Local-Tenant-Id": "local-tenant",
            "X-Local-Principal-Id": "local-admin",
            "X-Local-Roles": "RateLimit.Admin",
        }
    examples = Path(__file__).resolve().parents[1] / "examples"
    with httpx.Client(timeout=30, follow_redirects=False, headers=headers) as client:
        for collection in ("prices", "policies"):
            records = json.loads((examples / f"{collection}.json").read_text())
            for record in records:
                record_id = quote(record["id"], safe="")
                if args.apply:
                    response = client.put(
                        f"{settings.seed_api_url.rstrip('/')}/{collection}/{record_id}",
                        json=record,
                    )
                    response.raise_for_status()
                    print(f"Saved {collection}/{record_id}")
                else:
                    print(json.dumps({"collection": collection, "record": record}))
    if not args.apply:
        print("Dry run only. Prices are illustrative, not actual Azure prices.")


if __name__ == "__main__":
    main()
