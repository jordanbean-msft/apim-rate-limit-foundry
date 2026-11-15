---
title: Azure topology and trust
description: Resource topology, identity boundaries, and network responsibilities for the AI gateway.
---

## Architecture views

The editable [logical and physical draw.io diagrams](diagrams/README.md)
show runtime flows, Terraform resource placement, private endpoints and identity
grants. The physical view includes public-development differences and does not
claim to be a live Azure inventory.

Terraform composes APIM, a direct Azure OpenAI account/deployments, two Python
Function hosts, Redis, Table Storage, a Node/React portal, Key Vault, Event Hubs,
Application Insights and Log Analytics. Model routing uses native APIM backend IDs.

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
requires Gateway/Admin/Reader roles. The stream-to-APIM logging callback is limited
to the configured Function identity, not any user with a delegated API token.
APIM alone has Sender permission to the Event Hub.

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

Private deployments need APIM-to-Function, Function-to-model/storage/Redis and
APIM-to-Event-Hub connectivity, including DNS. The streaming callback also needs
Function-to-APIM connectivity. Validate that path explicitly; do not bypass the
gateway by adding a direct Python Event Hub publisher when callback egress fails.

## Cloud boundaries

Use explicit Commercial or Government authorities, API audiences and endpoint
suffixes. Verify regional support for APIM tier, Event Hub identity/private
networking and OpenAI protocols before deployment. An available Commercial
feature does not imply Government parity or GCCH certification.

## Cutover

See [migration](migration.md) before applying deletions. The new deployment does
not ingest historical monetary holds or relabel application spend as user spend.
The deployment plan must be reviewed before resource destruction/replacement.
