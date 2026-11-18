---
title: Azure topology and trust
description: Resource topology, identity boundaries, and network responsibilities for the AI gateway.
---

## Architecture views

The editable [logical and physical draw.io diagrams](diagrams/README.md)
show runtime flows, Terraform resource placement, private endpoints and identity
grants. The physical view illustrates private deployment; public-development
differences remain in supporting documentation. Neither view is a live Azure
inventory.

Terraform composes APIM, a direct Azure OpenAI account/deployments, two Python
Function hosts, Redis, Table Storage, a Node/React portal, Key Vault, Event Hubs,
Application Insights and Log Analytics. Model routing uses native APIM backend IDs.

A model alias that lists additional endpoints (the same model in another Azure
OpenAI account or region) is served by a native APIM **backend pool**: one backend
per member with a circuit breaker (429/5xx, `Retry-After` honored), plus a
`Pool` backend with member priority and weight. Nonstreaming requests retry on
429/5xx so another member is tried. Streaming goes through the Function relay to
the primary endpoint only, so it gets no pool failover. Accounting stays per model.
Single-endpoint aliases keep one plain backend. See [model registry](model-registry.md).

Redis holds shared cached configuration and live approximate spend/context/replay
state. Warm admission has no Table dependency; cold configuration misses may read
Table and Admin configuration writes remain synchronous durable-first. Request
and usage Table mirrors use a bounded process-local background writer, not a
new Azure queue service. Storage queue endpoints/permissions also serve Function
hosting; they do not imply a durable accounting queue or outbox. Redis loss can
reset spend, and lost background writes can leave reports permanently incomplete.

## Identity boundaries

Inference requires an Entra user token plus a validated inference-product key.
Tenant and user object ID come from the validated token. APIM subscription ID is
application attribution; primary/secondary keys do not create new users or budgets.

APIM's user-assigned identity calls the budget/stream Functions and Azure OpenAI.
Function Easy Auth validates platform tokens and application code independently
requires Gateway/Admin/Reader roles. Only the Function identity has Sender
permission to the Event Hub, scoped to the hub; APIM has no Event Hub role.

The portal proxy keeps its product key server-side through Key Vault and
forwards each user's delegated token. Admin CRUD and Reader scoping remain
server decisions. A browser role hint or filter is not authorization.
The Function's dashboard/workspace Reader permissions are not delegated to
ordinary portal Readers.

## Networking

Deployment explicitly chooses public development access or private-only access.
VNets/subnets/resource groups already exist. Private endpoint DNS zone groups
and virtual network links are owned by Azure policy, not this Terraform.
Every private endpoint ignores `private_dns_zone_group` drift.

Private deployments need APIM-to-Function and Function-to-model/storage/Redis/
Event-Hub connectivity, including DNS. The budget and streaming Functions publish
usage events directly to the Event Hub namespace, so both need private connectivity
to it. APIM also needs private connectivity to every additional pool member account.

## Cloud boundaries

Use explicit Commercial or Government authorities, API audiences and endpoint
suffixes. Verify regional support for APIM tier, Event Hub identity/private
networking and OpenAI protocols before deployment. An available Commercial
feature does not imply Government parity or GCCH certification.

## Deployment safety

Review the Terraform plan before resource destruction or replacement. Preserve
stored accounting data and verify compatibility before changing deployed schemas.
Continue with [deployment](deployment.md) for the execution sequence,
[architecture](../ARCHITECTURE.md) for runtime decisions and
[operations](operations.md) for failure handling.
