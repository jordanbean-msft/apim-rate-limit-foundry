import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from apim_rate_limit_foundry.accounting import (
    actual_debits,
    debits,
    digest,
    matching,
    validate_estimate,
)
from apim_rate_limit_foundry.config import Settings
from apim_rate_limit_foundry.models import Assignment, Decision, Policy, Price, Reserve, Settle
from apim_rate_limit_foundry.stores.contracts import Conflict, CounterStore, Record, Repository

logger = logging.getLogger(__name__)


def event(kind: str, record_id: str, tenant: str, principal: str, data: Record) -> Record:
    return {
        "id": record_id,
        "kind": kind,
        "tenant_id": tenant,
        "principal_id": principal,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }


class Engine:
    def __init__(self, repository: Repository, counters: CounterStore, settings: Settings) -> None:
        self.repository = repository
        self.counters = counters
        self.settings = settings

    async def configuration(self, collection: str) -> list[Record]:
        return [r for r in await self.repository.list(collection) if not r.get("_deleted")]

    async def reserve(self, request: Reserve) -> Decision:
        validate_estimate(request, self.settings)
        reservation_id = digest(request.tenant_id, request.principal_id, request.request_id)
        fingerprint = digest(request.model_dump_json())
        intent = await self.repository.get("intents", reservation_id)
        if intent is None:
            policies = matching(
                request,
                [Policy.model_validate(p) for p in await self.configuration("policies")],
                [Assignment.model_validate(a) for a in await self.configuration("assignments")],
            )
            if not policies:
                raise ValueError("No matching policy; admission denied")
            prices = [
                Price.model_validate(p)
                for p in await self.configuration("prices")
                if p["service"] == request.service
                and p["model"] == request.model
                and (request.price_version is None or request.price_version == p["version"])
            ]
            if len(prices) != 1:
                raise ValueError("Exactly one matching price version is required")
            price = prices[0]
            now = datetime.now(UTC)
            charges = debits(request, policies, price, now)
            reset = min(d["reset_at"] for d in charges)
            retry_after = max(1, int((datetime.fromisoformat(reset) - now).total_seconds()) + 1)
            decision = Decision(
                allowed=True,
                reservation_id=reservation_id,
                reason="reserved",
                reset_at=reset,
                retry_after=retry_after,
                matched_policy_ids=[d["policy_id"] for d in charges],
            ).model_dump(exclude={"denied_policy_ids"})
            candidate = event(
                "intent",
                reservation_id,
                request.tenant_id,
                request.principal_id,
                {
                    "request": request.model_dump(mode="json"),
                    "fingerprint": fingerprint,
                    "debits": charges,
                    "price": price.model_dump(mode="json"),
                    "decision": decision,
                },
            )
            # Persist the maximum liability before touching Redis. Incomplete intents replay
            # conservatively after cache loss, including crashes before the admission reply.
            intent = await self.repository.create("intents", reservation_id, candidate)
        data = intent["data"]
        if data["fingerprint"] != fingerprint:
            raise Conflict("Request ID reused with different request")
        if any(d["reset_at"] <= datetime.now(UTC).isoformat() for d in data["debits"]):
            return Decision(
                allowed=False,
                reason="reservation_window_expired",
                reservation_id=reservation_id,
                reset_at=data["decision"]["reset_at"],
            )
        decision = await self.counters.reserve(
            reservation_id, fingerprint, data["debits"], data["decision"]
        )
        decision["headers"] = {
            "X-RateLimit-Remaining": str(decision["remaining"]),
            "X-RateLimit-Reset": decision["reset_at"],
            "X-RateLimit-Estimated": "true",
            "X-RateLimit-Policies": ",".join(decision.get("matched_policy_ids", [])),
        }
        if not decision["allowed"]:
            decision["retry_after"] = max(
                1,
                int(
                    (
                        datetime.fromisoformat(decision["reset_at"]) - datetime.now(UTC)
                    ).total_seconds()
                )
                + 1,
            )
            decision["headers"]["Retry-After"] = str(decision["retry_after"])
            decision["headers"]["X-RateLimit-Denied-Policies"] = ",".join(
                decision.get("denied_policy_ids", [])
            )
        else:
            decision["retry_after"] = 0
        # An allow is not returned until its immutable durable usage event exists.
        await self.repository.create(
            "usage",
            reservation_id,
            event(
                "reservation",
                reservation_id,
                request.tenant_id,
                request.principal_id,
                {
                    **data,
                    **decision,
                    "status": "reserved" if decision["allowed"] else "denied",
                    "estimated": True,
                },
            ),
        )
        logger.info(
            "rate_decision",
            extra={
                "reservation_id": reservation_id,
                "allowed": decision["allowed"],
                "service": request.service,
            },
        )
        return Decision.model_validate(decision)

    async def settle(self, request: Settle) -> Record:
        intent = await self.repository.get("intents", request.reservation_id)
        if intent is None:
            raise Conflict("Unknown reservation")
        data = intent["data"]
        original = Reserve.model_validate(data["request"])
        cached_reported = request.status == "actual" and (
            "cached_input_tokens" in request.usage.model_fields_set
        )
        if request.status == "actual":
            required = {
                "foundry": {"input_tokens", "output_tokens"},
                "document-intelligence": {"pages"},
                "language": {"text_records"},
            }[original.service]
            if not required.issubset(request.usage.model_fields_set):
                raise ValueError("Actual usage is missing required service counters")
            for name in ("input_tokens", "output_tokens", "pages", "text_records", "requests"):
                if getattr(request.usage, name) > getattr(original.usage, name):
                    raise ValueError("Actual usage exceeds admitted hard bound; retain reservation")
            charges = actual_debits(
                data["debits"],
                Price.model_validate(data["price"]),
                request.usage,
                conservative_input=not cached_reported,
            )
        else:
            charges = data["debits"]
        estimated = request.status != "actual" or (
            original.service == "foundry" and request.usage.input_tokens > 0 and not cached_reported
        )
        fingerprint = digest(request.model_dump_json(), str(cached_reported))
        counter = await self.counters.finalize(request.reservation_id, charges, fingerprint)
        result = event(
            "settlement",
            request.reservation_id,
            intent["tenant_id"],
            intent["principal_id"],
            {
                "status": request.status,
                "estimated": estimated,
                "cached_input_reported": cached_reported if original.service == "foundry" else None,
                "reservation_id": request.reservation_id,
                "usage": request.usage.model_dump(),
                "debits": charges,
                "counter": counter,
                "fingerprint": fingerprint,
            },
        )
        persisted = await self.repository.create("settlements", request.reservation_id, result)
        if persisted["data"]["fingerprint"] != fingerprint:
            raise Conflict("Reservation already durably finalized differently")
        await self.repository.create("reconciliation", request.reservation_id, result)
        return persisted

    async def release(self, reservation_id: str) -> Record:
        intent = await self.repository.get("intents", reservation_id)
        if intent is None:
            raise Conflict("Unknown reservation")
        # The shared release contract contains no proof that dispatch did not happen.
        # Therefore release finalizes the liability, never silently refunds it.
        return await self.settle(
            Settle(
                reservation_id=reservation_id,
                usage=Reserve.model_validate(intent["data"]["request"]).usage,
                status="conservative",
            )
        )

    async def reconcile(self) -> int:
        count = 0
        for intent in await self.repository.list("intents"):
            record_id = intent["id"]
            if await self.repository.get("settlements", record_id):
                continue
            usage_event = await self.repository.get("usage", record_id)
            if usage_event is None or not usage_event["data"]["allowed"]:
                continue
            if max(d["reset_at"] for d in intent["data"]["debits"]) > datetime.now(UTC).isoformat():
                continue
            await self.release(record_id)
            count += 1
        return count

    async def recover(self) -> Record:
        token = await self.counters.begin_recovery()
        records: list[Record] = []
        for intent in await self.repository.list("intents"):
            data = intent["data"]
            usage_event = await self.repository.get("usage", intent["id"])
            settlement = await self.repository.get("settlements", intent["id"])
            if settlement:
                counter = settlement["data"]["counter"]
            else:
                usage_data = usage_event["data"] if usage_event else {}
                allowed = usage_data.get("allowed") is True
                proven_denial = (
                    usage_data.get("allowed") is False
                    and usage_data.get("reason") == "budget_exhausted"
                )
                recorded_decision = {
                    name: usage_data[name] for name in Decision.model_fields if name in usage_data
                }
                counter = {
                    "fingerprint": data["fingerprint"],
                    "final": "",
                    "decision": {
                        **data["decision"],
                        **recorded_decision,
                        "allowed": allowed,
                        "remaining": 0,
                        "reason": "budget_exhausted"
                        if proven_denial
                        else "recovered_conservatively",
                    },
                    # A retry denied by recovery is not proof that the original
                    # ambiguous attempt incurred no liability.
                    "debits": [] if proven_denial else data["debits"],
                }
            records.append({"id": intent["id"], "counter": counter})
        # Durable recovery audit must succeed before reopening the admission gate.
        result = event(
            "recovery", uuid4().hex, "*", "*", {"status": "recovered", "records": len(records)}
        )
        await self.repository.create("audit", result["id"], result)
        await self.counters.recover(token, records)
        return result

    async def bind_operation(self, payload: dict[str, Any]) -> Record:
        intent = await self.repository.get("intents", payload["reservation_id"])
        admitted = await self.repository.get("usage", payload["reservation_id"])
        if intent is None or admitted is None or not admitted["data"]["allowed"]:
            raise Conflict("Unknown admitted reservation")
        request = intent["data"]["request"]
        if request["service"] != "document-intelligence" or any(
            payload[k] != request[k] for k in ("tenant_id", "principal_id", "model")
        ):
            raise Conflict("Operation identity does not match reservation")
        record_id = digest(payload["operation_id"])
        old = await self.repository.create("operations", record_id, payload)
        if old != payload:
            raise Conflict("Operation already bound differently")
        return {"allowed": True}

    async def check_operation(self, payload: dict[str, Any]) -> Record:
        old = await self.repository.get("operations", digest(payload["operation_id"]))
        allowed = old is not None and all(old.get(k) == v for k, v in payload.items())
        return {
            "allowed": allowed,
            **({"reservation_id": old["reservation_id"]} if allowed and old else {}),
        }

    async def report(
        self, collection: str, tenant: str, principal: str, admin: bool
    ) -> list[Record]:
        if collection == "usage":
            records = await self.repository.list("usage")
            for record in records:
                settled = await self.repository.get("settlements", record["id"])
                if settled:
                    record["data"].update(
                        {
                            k: v
                            for k, v in settled["data"].items()
                            if k
                            in ("debits", "status", "estimated", "usage", "cached_input_reported")
                        }
                    )
        else:
            records = await self.repository.list(collection)
        scoped = [
            r
            for r in records
            if admin or (r.get("tenant_id") == tenant and r.get("principal_id") == principal)
        ]
        # Internal counter snapshots and fingerprints are not portal contracts.
        result = json.loads(json.dumps(scoped))
        for record in result:
            for name in ("counter", "fingerprint", "price", "decision"):
                record["data"].pop(name, None)
        return result
