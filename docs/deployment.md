# Deployment

Deployment uses **azd + Terraform** with remote state in Azure Blob Storage.
The resource group, network and private DNS policies are pre-created.
Do not provision directly from an unconfigured environment.

1. Select the intended Azure cloud, tenant, subscription, region and existing group.
2. Set azd remote-state coordinates (`RS_RESOURCE_GROUP`, `RS_STORAGE_ACCOUNT`,
   `RS_CONTAINER_NAME`) and explicit infrastructure inputs.
3. Configure OpenAI deployment aliases, price versions, Event Hub sizing/retention,
   APIM logger identity, private connectivity and portal identity.
4. Follow [migration](migration.md) for existing deployments. Use a new accounting
   Table/namespace rather than reading historical data with the new schema.
5. Run local validation and review the Terraform plan, especially resource
   deletions/replacements. Preserve unrelated hosting drift and existing model
   deployments unless intentionally changing them.
6. Run `azd provision` and `azd deploy` only against that reviewed environment.
7. Seed reviewed organization/assignment/price/budget records through the
   authenticated portal API; the seed tool defaults to preview.
8. Rebuild counters and execute the [operational acceptance checks](operations.md).

The managed model account is direct Azure OpenAI (`OpenAI`, S0), not a Foundry
project/ML hub. Routing preserves the native `.openai.azure.com` origin in
Commercial and the explicitly verified sovereign equivalent in Government.
The current native APIM backend-ID routing is retained.

APIM native Event Hub logging uses managed identity, not a connection string
secret. Verify Sender RBAC, logger identity settings and network reachability.
The retained streaming host calls the internal APIM logging operation after
recording terminal usage; this path must work in private networking too.

Terraform outputs feed application settings through azd. See the
[infrastructure reference](../infra/README.md) for exact variables. Never deploy
local auth bypasses, copy `.env` to Function settings, or expose the portal's
server product key to the browser.

Cloud parity, interactive MFA/client integration and live policy compilation must
be verified in the target environment. This sample makes no GCCH/FedRAMP
certification, strict spending-cap or exactly-once Event Hub delivery claim.
