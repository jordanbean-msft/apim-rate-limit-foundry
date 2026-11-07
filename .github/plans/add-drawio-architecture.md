# Add editable draw.io architecture diagrams

## Scope

Create native, editable logical and physical architecture files with checked-in
SVG previews. Keep the existing guides canonical; replace redundant overview
Mermaid blocks where a draw.io view now owns that concern, while retaining useful
sequence diagrams. No application, Terraform, deployment or identity changes.

## Checklist

- [x] Verify implementation/resource boundaries and native draw.io tooling.
  Owner: main agent. Use current source and the read-only Commercial inventory.
- [x] Create `docs/diagrams/logical-architecture.drawio`: clients, gateway,
  reserve/settle, streaming, state, administration and telemetry responsibilities.
- [x] Create `docs/diagrams/physical-architecture.drawio`: deployed Commercial
  public-demo page plus a clearly non-deployed private-network reference page.
  Distinguish shared plans/identities and cloud/provider constraints.
- [x] Export readable, self-contained SVGs using native draw.io; inspect each
  rendered page and verify editable XML, containment, connectors and resource map.
- [x] Update README, architecture, topology and deployment/component references;
  document local editing and reproducible export without a hosted editor.
- [x] Validate links, XML/SVGs and scoped hooks; preserve unrelated changes.
  Passed: 293 links/anchors across 15 guides, 23 shell examples, XML graph/
  containment checks, embedded source/export consistency, label-width checks,
  offline Chromium rendering of all three SVGs, visual inspection and scoped
  pre-commit hooks. Generated SVGs received the existing EOF normalization.

## Acceptance

Native sources and previews are persistent repository files. Labels describe
implemented behavior, not an aspirational production topology. Identity and
telemetry edges are distinct from inference; Table/Redis are not drawn as a
distributed transaction; cached tokens change settlement, not provider quota.
The physical private view must show outbound app VNet integration separately from
private ingress, classic APIM internal injection, and policy-owned DNS.
