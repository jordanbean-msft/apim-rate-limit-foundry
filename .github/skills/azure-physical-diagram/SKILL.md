---
name: azure-physical-diagram
description: 'Create or restyle editable Azure deployment diagrams with dashed scopes and icon tiles - Brought to you by jordanbean-msft/apim-rate-limit-foundry'
---

# Azure physical diagram

## Overview

Use this skill when creating or updating a physical Azure architecture diagram,
restyling a draw.io deployment diagram, or matching the established physical
deployment style. Produce editable draw.io XML, not a flattened screenshot.

The style uses a white canvas, dark navy Segoe UI text, square dashed scope
boundaries, pale blue VNets, a pale purple identity band, compact official
Microsoft service icons, and color-coded right-angle connectors.

Transfer visual conventions from a reference, never its application-specific
resources, names, identifiers, addresses, environment count or security claims.

## Prerequisites

* Read the target repository's instructions and the existing diagram.
* Use Terraform, Bicep or another authoritative resource definition to establish
  placement, dependencies, networking, identities and optional resources.
* Obtain the reference diagram if the user specifies one. Ask for an accessible
  path or attachment if it cannot be read; do not claim a visual match unseen.
* Use existing embedded official Microsoft SVG icons where possible. If new
  icons are needed, locate the user's Microsoft icon library or an approved
  Microsoft distribution. Do not fetch or upload private diagrams to a service.
* Use draw.io Desktop or an already-installed local renderer for validation.
  Windows, Linux and macOS draw.io Desktop support command-line export.
  In WSL, translate paths with `wslpath -w` for the Windows executable.

## Quick start

1. Inventory the existing pages, component IDs, parent relationships, connectors,
   embedded icons and `Source` / `IconSource` metadata. Decode compressed draw.io
   pages locally when necessary.
2. Read the source infrastructure. Separate pre-existing resources, provisioned
   resources, references, conditional resources and operator-managed services.
3. If a reference is supplied, inspect both its XML styles and a local render.
   Extract layout grammar and style tokens without copying application content.
4. Arrange the deployment page using the layout below. Preserve other existing
   pages and apply the same visual language to them.
5. Use the measured style tokens and XML recipes below. Keep resource labels
   short; put implementation detail in captions, tooltips or a side note.
6. Export and inspect every changed page. Fix layout defects and repeat until
   the acceptance checks pass.

## Layout

* Put a left-aligned title at the upper left and a muted one-line subtitle below.
  The subtitle identifies scope, environment and important variants.
* Place a compact client-access box at upper left. Put the Entra tenant band
  across the top of the main deployment columns. Keep this band for tenant-scoped
  app registrations and enterprise applications, not Azure managed-identity
  resources.
* Keep the default view focused on deployed resources and their relationships.
  Do not add boxes for public-development variants, networking policy, placement
  explanations, DNS responsibilities, runtime behavior, cloud alternatives,
  connector legends or referenced model resources unless explicitly requested.
  Keep those details in supporting documentation or concise tooltips.
* Use a narrow left sidebar for actual deployment tooling, with its proper icon
  and a short label. Do not invent a CI/CD stack.
* Nest subscription, resource group, VNet and subnet scopes. Keep the resource
  group and VNet ownership explicit when the infrastructure only references them.
  Do not imply that referenced subnet IDs must belong to the application group.
* Put subnet-resident workloads and private endpoint NICs in their actual
  subnet. Put PaaS resources in a services panel outside the VNet.
* Put every user-assigned managed identity inside its Azure resource group,
  outside the VNet. This includes conditional model-account identities, not only
  workload identities. On deployment pages, put their standalone icon tiles
  inside the Services shape alongside the other services, not below that shape
  or inside a separate managed-identity block or per-identity boundary.
  Identity-detail pages keep the tiles inside the resource-group scope.
* Put outbound-integration subnets near their corresponding PaaS hosts. Connect
  the hosts or hosting plans to NIC icons inside the integration subnets, without
  implying VM placement. Label these as platform-managed virtual integration
  interfaces, not separately provisioned NIC resources or inbound endpoints.
* Place service icons in evenly spaced rows with bold centered labels beneath
  them, followed by short muted captions. Avoid rounded, text-heavy service cards.
* Omit empty sidebars and shrink the canvas after removing explanatory panels.
  An unboxed row of managed-identity tiles can sit inside the services panel.
* Repeat the same aligned deployment column for each environment only when those
  environments exist in the source. Never copy a reference's environment count.
* Use separate pages for identity grants or materially different topologies when
  one page becomes crowded. Identity pages use the same icon tiles and purple
  scope family; grant arrows are not network paths.
* Leave gutters for connectors. Increase the page rather than shrinking text
  below 10px or routing through labels.

An initial single-environment canvas can be approximately 1640 x 1980 diagram
units. A useful starting point is a 330-unit tooling sidebar, a 1170-unit
deployment column and 50-70-unit gutters. Add a separate external-services
column only when requested. These are starting proportions, not fixed dimensions.

## Style tokens

| Element | Style |
| --- | --- |
| Canvas | White `#FFFFFF`; no shadow; hidden grid; Segoe UI |
| Title | Bold, 28px, navy `#000041` |
| Subtitle | 12-13px, gray `#75757A` |
| Boundary heading | Bold, 13-15px, navy; small icon at top left |
| Component label | Bold, 11.5-12px, navy; centered under icon |
| Caption | 10-11px, gray; centered; usually 1-3 lines |
| General boundary | Square; 1.4px stroke; `dashed=1;dashPattern=4 3` |
| Subscription | White fill, `#91A7BF` stroke |
| Resource group | `#F7F9FB` fill, `#9EA7B0` stroke |
| VNet | `#E4EEFC` fill, `#0078D3` stroke |
| Subnet | White fill, `#8AA9CC` stroke |
| Services panel | White fill, `#BAC3CC` stroke |
| Identity band | `#F6F2FA` fill, `#A994BA` stroke |
| Nested identity scope | `#F9F7FC` fill, `#BCADCB` stroke |
| Client access | `#F1F6FC` fill, `#91A7BF` stroke |
| Deployment tooling | `#FFF8E8` fill, `#BE9D48` stroke |
| DNS / neutral note | `#F4F7FA` fill, `#A7B3C0` stroke |
| Application / HTTPS path | Blue `#0078D3`, solid, 2px |
| Identity / token path | Purple `#5C2D91`, solid, 2px |
| Identity grant / federation | Purple `#5C2D91`, dashed, 2px |
| Private Link / association | Slate `#587B9D`, dashed, 2px |
| Optional data / analytics path | Green `#107C10`, 2px |
| Optional deployment path | Amber `#A16C00`, 2px |

Use 24px header icons and 30-40px component icons. Preserve the icon's original
aspect ratio, colors and artwork. A transparent, borderless parent group can
contain the icon, label and caption as separate editable cells.

Dashed boundaries denote scope. Label dashed connectors with their relationship;
they do not automatically mean optional traffic and do not require a legend box.
Mark conditional components with `*` and explain the condition nearby.

## Identity and icon semantics

Verify identity dependencies from source, not from assumptions about Azure
hosting. Look for application registrations, service principals, delegated scopes,
app roles, federated credentials and managed-identity assignments. In Terraform,
inspect `azuread_application`, `azuread_service_principal`,
`azuread_application_federated_identity_credential` and
`azurerm_user_assigned_identity` resources. Show separate registrations when
the application has separate API and portal registrations.

Use the icon matching the object, rather than one generic Entra glyph for every
identity-related shape. Useful relative paths in the local icon library are:

| Object | Icon |
| --- | --- |
| Entra ID tenant | `Microsoft Entra/Architecture Icons Oct 2023/Microsoft Entra ID color icon.svg` |
| App registration | `identity/10232-icon-service-App-Registrations.svg` |
| Enterprise application / service principal | `identity/10225-icon-service-Enterprise-Applications.svg` |
| User-assigned managed identity | `identity/10227-icon-service-Entra-Managed-Identities.svg` |
| Azure subscription | `general/10002-icon-service-Subscriptions.svg` |
| VNet integration virtual interface | `networking/10080-icon-service-Network-Interfaces.svg` |
| Terraform tooling | `More Icons/logos/terraform.svg` |

These are asset lookup hints, not required absolute paths. If unavailable, locate
an approved equivalent of the same semantic icon. Use the current Entra ID glyph
instead of the legacy Azure Active Directory diamond. Do not substitute the
subscription key icon for a managed identity, or a tenant icon for a registration.
Add the subscription icon to its boundary heading and the Terraform logo to the
deployment-tooling box. Embed all assets and record their provenance.

Azure UAMI resources belong to a subscription and resource group even though
they have backing Entra service principals. Do not move the Azure resource into
the tenant band or draw a managed identity as an application registration.
App registrations and enterprise applications are tenant-scoped, not
resource-group resources.

## Draw.io XML recipes

Write an uncompressed `mxfile` with one `diagram` / `mxGraphModel` per page.
Use stable unique IDs and real `parent`, `source` and `target` references.
Nest cells using parent-relative geometry; keep children inside their parent.

Use this container style, substituting the palette's fill and stroke:

```text
rounded=0;html=1;whiteSpace=wrap;fillColor=#E4EEFC;strokeColor=#0078D3;strokeWidth=1.4;dashed=1;dashPattern=4 3;container=1;collapsible=0;recursiveResize=0;
```

Use separate text cells for boundary headings and component labels:

```text
text;html=1;whiteSpace=wrap;align=center;verticalAlign=middle;fontFamily=Segoe UI;fontSize=12;fontColor=#000041;fontStyle=1;spacing=0;
```

Embed SVG data in the image cell instead of linking a local file or website.
Reuse the existing diagram's encoding; `imageAspect=1;aspect=fixed` preserves
proportions. Retain the original icon's relative path in `IconSource`.
Retain implementation paths in `Source`. Keep detailed original labels in
tooltips when replacing cards with concise tiles.

Use this connector style, adjusting color, dashes and terminal anchor fractions:

```text
edgeStyle=none;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#0078D3;strokeWidth=2;dashed=0;fontFamily=Segoe UI;fontSize=10.5;fontStyle=2;fontColor=#0078D3;labelBackgroundColor=#FFFFFF;jumpStyle=arc;exitX=1;exitY=0.5;entryX=0;entryY=0.5;exitPerimeter=0;entryPerimeter=0;
```

With `edgeStyle=none`, supply explicit waypoints so every segment is horizontal
or vertical, including the first and last segment. Set `relative="1"` on edge
geometry and place the edge at the nearest common ancestor of its terminals.
Use a small label offset to keep the white label background from hiding short
connectors. For long vertical gutter routes, `horizontal=0` rotates the label.
Do not let rotated labels extend into neighboring panels.

## Topology rules

* Match the source deployment, not an idealized Azure architecture.
* Do not add a Front Door, WAF, VPN, Bastion, NAT gateway, subnet, private endpoint,
  DNS zone, managed identity or queue merely because it appears in the reference.
* Distinguish an injected APIM instance from an APIM private endpoint.
* Distinguish App Service / Function outbound VNet integration from inbound
  Private Link and from the physical hosting of the service. A conceptual NIC
  icon for integration does not assert an `azurerm_network_interface` resource.
* Show private endpoint targets and subresources accurately. A storage account
  can have separate blob, queue, table and file endpoints.
* Distinguish created model accounts from referenced accounts; private
  connectivity to a referenced account may be outside the deployment's scope.
* Show workspace-based Application Insights as linked to its workspace. Do not
  invent a diagnostic export back to that same workspace or a Monitor Private
  Link Scope.
* Keep identity grants, network reachability and application authorization
  distinct. Do not imply that a grant creates connectivity.
* Describe operator-owned routing and policy-managed DNS in documentation or
  tooltips without adding explanatory panels to the default deployment view.
* Do not present configured topology as a verified live deployment inventory.
* Preserve cloud-specific alternatives rather than drawing a connection between
  Commercial and Government deployments.

## Suggested CIDR annotations

When asked for subnet recommendations, verify current Microsoft guidance for the
actual SKU, operating system and hosting plan. Distinguish minimum supported sizes
from recommended sizes and from sample-specific growth allowances. Account for
Azure-reserved addresses, combined integration demand, temporary scaling /
maintenance capacity, and each private-endpoint IP configuration.

Put CIDRs in the VNet and subnet headings and mark them `suggested` unless
verified from deployment state. Use valid, non-overlapping RFC1918 subnet ranges
contained in the example VNet; require enterprise IPAM / connectivity checks
before use. Keep the existing-network ownership unchanged. Document sizing
rationale and official sources alongside the diagram, not in new callout boxes.
Never turn a diagram suggestion into infrastructure changes without a request.
Validate ranges programmatically and render headings to check text wrapping.

## Validation and acceptance

* Parse every changed XML page successfully. Check unique IDs, existing parents
  and terminals, positive dimensions, and child / page containment.
* Compare component inventory, source metadata, icon provenance, conditions and
  trust boundaries with the original and the source infrastructure.
  Account for intentionally removed explanatory panels instead of restoring them.
* Check that unboxed UAMI tiles are inside the Services shape on deployment
  pages and inside the resource-group scope on identity-detail pages. App
  registrations stay in the tenant band, Entra-related icons match their object
  types, and the Azure subscription and actual deployment tooling have their
  corresponding icons.
* Check that each outbound-integration subnet contains a NIC icon, that its host
  connector terminates at the icon, and that its caption identifies the interface
  as platform-managed rather than a separately provisioned resource.
* Confirm every image is embedded and the diagram works without the icon library.
* Render every changed page locally. For example, with draw.io Desktop on PATH:

  ```sh
  drawio --export --format png --page-index 1 --scale 1 --output /tmp/physical-preview.png diagram.drawio
  ```

* Use `--page-index 2` and later indexes for additional pages. A local SVG export
  can help check label extents. Use a session-specific `--user-data-dir` if an
  existing Electron session causes profile contention.
* Inspect title hierarchy, boundary nesting, icon alignment, clipped labels,
  connector visibility, right-angle routing, arrow endpoints and crossings.
  XML validity alone does not establish a visual match.
* Fix defects and re-render affected pages. If rendering is unavailable, state
  that visual validation remains incomplete.
* Keep scratch exports out of source control unless the user requests them.
  Update the diagram's existing maintenance documentation and return links to
  the diagram and any requested reusable artifacts.

## Troubleshooting

* If a Windows path is inaccessible from a remote Linux host, request an upload
  or a mounted path rather than substituting an unrelated diagram.
* If labels disappear, increase their geometry and inspect the render; do not
  conceal overflow or shrink all text to force a fit.
* If an arrow disappears under its label, offset the label away from the segment.
* If a connector cuts through a heading, route through a reserved gutter.
* If a native Azure shape is unavailable, reuse an embedded official icon or ask
  for an approved source. Do not substitute an unrelated service icon.

> Brought to you by jordanbean-msft/apim-rate-limit-foundry
