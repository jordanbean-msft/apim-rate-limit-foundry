# Use APIM AI backends

## Checklist

- [x] Add APIM backend entities for direct Azure OpenAI and AI service endpoints.
- [x] Switch gateway inbound routing to `set-backend-service backend-id`.
- [x] Preserve managed identity authentication for each backend.
- [x] Add policy tests for backend IDs and direct OpenAI routing.
- [x] Provision and deploy the backend/policy change.
- [x] Send mixed allowed/denied traffic and verify dashboard telemetry.
