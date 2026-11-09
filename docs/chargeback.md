# Business-unit chargeback

Administrators configure departments, their business-unit and cost-center codes,
teams within departments, and users assigned to those teams. The accounting
context snapshots those dimensions and the price version when the request is
checked. Later membership or price edits do not rewrite history.

`GET /api/chargeback?month=YYYY-MM&format=json` returns scoped monthly groups.
Use `format=csv` for downstream finance import. Groups preserve business unit,
cost center, department, team, user reference, application subscription and model.

Sum **one cost per actual request**, not user plus team plus department counters.
Unknown requests are separately counted in `unknown_requests`; their cost is not
assumed zero. A complete chargeback period requires addressing unknown records
and reconciling the export to the authoritative usage ledger.

Event Hub events carry the same dimensions, token counts, price version,
micro-USD cost and stable event ID. Downstream consumers should deduplicate by
event ID, tolerate schema evolution and reconcile missing events to the ledger.
Native Event Hub publication is best effort; its absence is not evidence that
the user consumed nothing.

This is configured internal showback/chargeback, not an Azure invoice. Shared
platform hosting costs, taxes, discounts and currency conversion are outside
the sample. No external finance adapter or accounting platform is deployed.
