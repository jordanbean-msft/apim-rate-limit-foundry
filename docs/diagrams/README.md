# Editable architecture diagrams

The `.drawio` files are the editable sources; SVGs are generated previews used by
the guides. Open a preview at full size to read its labels.

| View | Editable source | Preview | Canonical explanation |
| --- | --- | --- | --- |
| Logical responsibilities, accounting, streaming, state and telemetry | [Logical architecture](logical-architecture.drawio), one page | [Logical SVG](logical-architecture.svg) | [Architecture](../../ARCHITECTURE.md) and [reservation mechanics](../reservation-system.md) |
| Commercial application-subscription configuration, including the portal proxy and Key Vault | [Physical architecture](physical-architecture.drawio), page 1: **Commercial public demo** | [Commercial SVG](physical-commercial.svg) | [Resource inventory and identity](../azure-topology.md#observed-commercial-demo-resource-map) |
| Private ingress, APIM injection, outbound integration and policy-owned DNS | Same [physical source](physical-architecture.drawio), page 2: **Private networking reference** | [Private SVG](physical-private.svg) | [Private/public networking](../azure-topology.md#private-networking-versus-public-demo-mode) |

The public view records the November 6, 2026 Commercial demo, not a recommended
production SKU. The private page is a configuration reference, **not an observed
deployment**. Neither establishes Government availability or GCCH compliance.
Cloud-specific gates remain in the [topology guide](../azure-topology.md#cloud-specific-boundaries).

## Edit locally

Open a source file in draw.io Desktop, or in VS Code with the repository-recommended
**Draw.io Integration** extension (`hediet.vscode-drawio`). Use the page tabs in
the physical source. No hosted editor or upload is required.

Keep components, text, connectors and containers editable rather than pasting a
screenshot. Preserve explicit line breaks and plain SVG text labels
(`html=0;whiteSpace=nowrap`); HTML/automatic-wrap labels can disappear in Markdown
SVG sanitizers. Physical symbols use the Azure library bundled with draw.io.

Change the `.drawio` source first, export its affected pages, and update the
owning guide if the architecture or deployment evidence changes. Do not edit an
SVG instead of its source. Detailed request/lifecycle sequences remain in the
existing guides rather than being duplicated here.

## Export previews

In the Desktop export dialog, select SVG, the current page, a white/light
background, embedded images and a copy of the diagram. Disable embedded fonts.
Export each physical page separately using the filenames above.

Equivalent commands, from the repository root with a working draw.io Desktop
installation/display:

```bash
DRAWIO=/path/to/drawio

export_diagram() {
  "$DRAWIO" --disable-update --disable-gpu --export --format svg \
    --theme light --border 20 --timeout 60 \
    --embed-diagram --embed-svg-images --embed-svg-fonts false \
    --page-index "$3" --output "docs/diagrams/$2.svg" \
    "docs/diagrams/$1.drawio"
}

export_diagram logical-architecture logical-architecture 1
export_diagram physical-architecture physical-commercial 1
export_diagram physical-architecture physical-private 2
```

Page indices are **one-based**. For a Windows executable invoked from WSL, convert
both input and output filenames to Windows paths with `wslpath -w`.

The checked-in exports embed their Azure images and editable page data without
external fonts, remote image requests or machine-specific file paths. After
exporting, inspect every affected page and check that all labels survive a
renderer without HTML `foreignObject` support.

## Implementation anchors

Logical boundaries follow [`Engine`](../../src/apim_rate_limit_foundry/engine.py),
the [control API](../../src/apim_rate_limit_foundry/api.py),
[streaming implementation](../../src/apim_rate_limit_foundry/streaming/),
and [APIM policies](../../apim/README.md).
Physical ownership follows [Terraform composition](../../infra/main.tf),
[hosting](../../infra/modules/hosting/main.tf), and
[private endpoints](../../infra/modules/private_endpoints/main.tf).
The [topology guide](../azure-topology.md) owns resource/identity details; the
[observability guide](../observability.md) owns telemetry and dashboard semantics.
