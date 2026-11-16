---
title: Architecture diagrams
description: Editable logical, physical, and identity views of the APIM AI gateway.
---

## Editable draw.io diagrams

Open the files in draw.io Desktop or the VS Code draw.io extension. Each file
contains two named pages. Shapes, connectors, labels and boundaries are editable.
The logical view uses application-level components. Both views use official
Microsoft service icons embedded as SVGs rather than external image links.

| File | Pages | Purpose |
| --- | --- | --- |
| [Logical architecture](logical-architecture.drawio) | Inference and accounting; Portal and reporting | Application requests and responses through the gateway, streaming, budget checks, portal settings and reports |
| [Physical architecture](physical-architecture.drawio) | Private deployment; Identity and access | Terraform resource placement, subnet integration, private endpoints, app registrations and managed-identity permissions |

The physical view illustrates `public_network_access_enabled=false`.
It describes the current configuration model, not a live deployment inventory.
Optional streaming and created versus referenced model resources are labeled
explicitly. PaaS resources remain outside the VNet; private endpoint NICs and
outbound integration are separate concepts.

The VNet and subnet layout is illustrative. This Terraform consumes existing
subnets through the `apim_subnet_id`, `functions_subnet_id`, `web_subnet_id` and
`private_endpoint_subnet_id` input variables and does not create the VNet,
subnets or private DNS zones.

## Physical deployment style

The physical diagram uses square dashed scope boundaries, a pale blue VNet,
a pale purple identity band, Segoe UI typography and compact service-icon tiles.
Subscription, resource group and network scopes nest explicitly. PaaS services
sit outside the VNet; private endpoint NICs sit inside their subnet. Workload and
conditional model-account UAMIs sit inside the Services shape within the resource
group, outside the VNet. They use the same standalone icon tiles as other services,
without a separate identity block. Integration
subnets contain NIC icons connected to their PaaS hosting plans. These represent
platform-managed outbound VNet integration interfaces, not separately provisioned
Azure NIC resources or inbound private endpoints.
The deployment-tooling box includes the Terraform logo. The subscription boundary
uses the Azure subscription icon.

The view omits explanatory boxes for public-development variants, network policy,
placement, private DNS routing, runtime behavior, cloud alternatives, connector
legends and referenced model resources. Those operational details remain in the
[topology guide](../azure-topology.md) and other supporting documentation.

Blue connectors show private access or outbound integration; purple connectors
show identity relationships. Slate dashed connectors show Private Link or
workspace associations. Labels distinguish relationships from runtime traffic.
The identity page uses the same palette and tile layout for authorization grants.

Use the repository's
[Azure physical diagram skill](../../.github/skills/azure-physical-diagram/SKILL.md)
to create or restyle future diagrams. Invoke `/azure-physical-diagram`, or ask
Copilot to use the Azure physical deployment diagram style. The skill includes
layout rules, exact colors, draw.io style recipes and local-render checks without
requiring the original reference application or its icon-library path.

## Suggested subnet address plan

The diagram labels an illustrative, non-overlapping plan within `10.42.0.0/22`.
These are suggestions, not deployed addresses or Terraform-managed network
resources. Confirm availability in enterprise IPAM and avoid overlap with
on-premises, peered and connected networks before provisioning.

| Subnet input | Suggested CIDR | Available addresses after Azure's five reservations | Sizing rationale |
| --- | --- | --- | --- |
| `apim_subnet_id` | `10.42.0.0/25` | 123 | Growth room for classic Developer / Premium internal VNet injection, including the internal load-balancer address |
| `functions_subnet_id` | `10.42.1.0/26` | 59 | Linux Elastic Premium / Dedicated integration baseline; budget and optional streaming hosts share the integration subnet |
| `web_subnet_id` | `10.42.2.0/26` | 59 | Recommended App Service integration size with scaling and platform-upgrade headroom |
| `private_endpoint_subnet_id` | `10.42.3.0/26` | 59 | Sample planning allowance for endpoint IP configurations and future additions, not an Azure-mandated prefix |

Microsoft's guidance covers
[classic APIM subnet sizing](https://learn.microsoft.com/en-us/azure/api-management/virtual-network-injection-resources#subnet-size),
[Functions subnet sizing by hosting plan](https://learn.microsoft.com/en-us/azure/azure-functions/functions-networking-options#subnets)
and [App Service integration capacity](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration#subnet-requirements).
Size integration subnets for the combined planned peak and temporary doubling
during scaling, plus platform maintenance. Choose a larger prefix allocation
(for example, `/25` or `/24` instead of `/26`) before integration if that capacity
is insufficient; the suggested `/26` is not a guarantee of every SKU's maximum
scale. Keep integration subnets delegated to `Microsoft.Web/serverFarms`;
the classic APIM and private-endpoint subnets must not use that delegation.
[Private endpoints](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview)
consume subnet addresses per service IP configuration; count storage subresources
separately. The remaining VNet space is unallocated growth capacity.

## Icons

Service icons come from the Microsoft Azure architecture icons and were embedded
without modification. Each icon shape records its relative original path in the
`IconSource` property. The files remain portable without access to the original
icon set or the internet.

The Azure OpenAI icon represents the actual `kind=OpenAI` account, not a Foundry
project or agent service. Both Azure Managed Redis and the Government Redis Cache
variant use their corresponding icons. The physical view uses the current
Microsoft Entra ID tenant icon and distinct icons for app registrations,
enterprise applications and Entra managed identities. Terraform and Microsoft Graph
use their respective logo assets. Generic notes and boundaries use ordinary
draw.io shapes rather than unrelated service icons.

## Application registrations

The app depends on two tenant-scoped app registrations and two corresponding
enterprise applications, created by the
[identity module](../../infra/modules/identity/main.tf):

* The API registration exposes `access_as_user` and the
  `RateLimit.Gateway`, `RateLimit.Admin` and `RateLimit.Reader` app roles.
* The portal registration requests delegated API access and Graph `User.Read`.
  Its federated identity credential uses the dedicated web UAMI for secretless
  App Service sign-in.

App registrations and enterprise applications remain in the Entra tenant band.
Their presence does not relocate Azure UAMI resources into the tenant scope.
The [AI module](../../infra/modules/ai/main.tf) also creates a separate
model-account UAMI when it creates the OpenAI account.

## Source mapping and maintenance

The logical view follows an application through the gateway to a model and back,
with streaming on a separate route and budget services below the main flow.
Both routes pass the gateway's initial budget check. The streaming relay reads
the saved Redis admission before calling the model, forwards chunks immediately,
and records actual usage directly in Redis through the shared accounting engine
at stream termination. It does not re-evaluate budgets per chunk or stop an active
stream when a monthly budget is crossed. The native token-rate policy is optional.
The portal page follows signed-in requests for settings and reports. Writer
internals, accounting edge cases and loss guarantees stay in the architecture
narrative rather than appearing as diagram callouts.

Component shapes include `Source` properties with implementation paths. Review
both views whenever the request flow, resources, identity grants or network
configuration changes. The primary evidence is:

* [Gateway policies and fragments](../../apim/)
* [Budget API and accounting engine](../../src/apim_rate_limit_foundry/)
* [Streaming Function entry point](../../stream/function_app.py) and [relay](../../src/apim_rate_limit_foundry/streaming/relay.py)
* [Portal proxy](../../web/server/api-proxy.mjs) and [browser session](../../web/src/CloudSession.tsx)
* [Terraform composition](../../infra/main.tf) and [resource modules](../../infra/modules/)

The [architecture narrative](../../ARCHITECTURE.md),
[topology and trust](../azure-topology.md) and
[observability guide](../observability.md) provide additional detail.
Existing Mermaid diagrams remain useful inline sequence views.

Monthly budgets are approximate operational caps against Redis-recorded spend,
not reservations. Warm admission never reads Table; only cold configuration
misses do. Durable-first Admin CRUD invalidates the shared configuration snapshot
(default 60s TTL). Redis holds admitted context/replay markers for 24h and monthly
user/team/department wildcard/model counters for about 62 days. Actual usage
increments all six counters atomically with its replay marker.

Redis unavailability fails closed `503`, with no Table fallback; exhausted budgets,
including zero limits, deny `429`. Data loss may reset spend and lose context;
there is no automatic ledger rebuild or global ledger lock. Request/usage Table
mirrors run in a bounded in-process async writer (256 pending; logged
drops/failures; best-effort 2s graceful-close drain), not awaited by APIM. Restart,
failure or saturation can lose writes; no durable queue/outbox/retry/exactly-once
guarantee exists. Live budgets and persisted history/chargeback may differ
permanently.

Streaming relays chunks incrementally, does Redis accounting in process at
terminal usage and schedules the APIM callback in the background. Nonstream
usage still waits briefly for Redis acceptance, not Table persistence. APIM alone
publishes best-effort Event Hub events: an event means Redis accepted usage, not
that Table persisted it. Preserve these distinctions when editing the diagrams.
