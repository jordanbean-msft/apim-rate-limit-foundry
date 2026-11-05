# Supporting three LLM API protocols

Extend the existing gateway end to end without changing Document Intelligence or Language behavior.
Preserve the current chat route, existing price records, durable reservations and consumer scoping.
Streaming remains conservative; do not parse/buffer SSE in APIM.

## Shared contracts and safety boundaries

- LLM `service` remains `foundry`. `Reserve.api_protocol` is optional for backward compatibility:
  `openai-chat`, `openai-responses`, or `anthropic-messages`; omitted Foundry protocol means chat.
  Non-LLM requests do not acquire a misleading protocol.
- Client routes: existing `/foundry/chat/completions`, new `/foundry/responses`, and
  `/anthropic/v1/messages`. Backends, deployment aliases, audiences, versions and catalog versions
  remain operator-pinned, never caller-selected.
- Normalized `Usage.input_tokens` is TOTAL input, including cache reads and writes.
  Existing `cached_input_tokens` means cache reads. Add `cache_write_input_tokens_5m` and
  `cache_write_input_tokens_1h`; their sum plus reads must not exceed total input.
- Price adds nullable `cache_write_5m_per_million` and `cache_write_1h_per_million`.
  Existing OpenAI prices remain valid. Anthropic conservative input pricing uses the maximum
  known uncached/read/write price, never assumes a discounted hit, and fails closed on unknown
  potentially billable prices. Prices remain administrator-maintained decimal strings.
- Actual `Settle` accepts either existing normalized `usage` OR a small `provider_usage` object,
  never both. Function derives the provider format from the original reservation protocol.
  APIM forwards ONLY backend usage metadata, never prompts or response content.
- OpenAI Chat uses prompt/completion tokens and prompt_tokens_details.cached_tokens.
  Responses uses input/output tokens and input_tokens_details.cached_tokens.
  Anthropic input_tokens EXCLUDES reads/writes: add cache_read_input_tokens and cache creation
  TTL breakdown to obtain normalized total. Never subtract cached reads from uncached twice.
  Incomplete/ambiguous usage retains conservative accounting rather than silently using zero.
- Support bounded inline text and client-executed function/tool definitions/results where safe.
  Reject opaque media/file/history references, background jobs and separately billed built-in
  tools rather than bypassing accounting. Never silently strip semantics-changing fields.
  Chat supports bounded max_tokens/max_completion_tokens, Responses max_output_tokens,
  and Messages max_tokens. Reject multiple generations.
- Anthropic tokenizers are not covered by the current OpenAI byte-token bound: reserve an
  explicit operator-verified model context input ceiling, with no claimed universal byte bound.
- Protocol implementation is portable, not a promise that every provider/API/model exists in
  Government. Optional endpoints need explicit verified capabilities; never route Government
  traffic to Commercial. Claude uses a separately referenced Foundry endpoint/managed identity,
  not an automatically created OpenAI resource or embedded Anthropic key.

## Execution checklist

- [ ] Backend owner: `src/`, `tests/`, root Function/package files only.
  Add protocols/usage normalization/cache writes, accurate cost/summary/recovery persistence,
  focused backwards-compatibility and malformed/incomplete-usage tests.
  Validate Ruff, formatting, mypy, warning-free tests and coverage.
- [ ] Gateway/infrastructure owner: `apim/`, `infra/`, `azure.yaml` only.
  Add all three bounded wire formats, raw-usage settlement, explicit operations/backend routing,
  cloud capability configuration, Anthropic version/auth headers and protocol contract/mock tests.
  Validate XML contracts, Terraform formatting/validation with zero diagnostics, mock plans/TFLint.
- [x] Portal owner: `web/` only.
  Add cache-write catalog editing/display, protocol-aware event inspection and cache unit visibility,
  representative demos and focused compatibility tests. Existing prices must not be forced to
  invent cache-write rates. Validate Node LTS lint/types/tests/build/audit.
- [ ] Parent integration: `examples/`, `scripts/`, docs, automation and this checklist.
  Update fixtures/seeding/client requests, all protocol documentation, VS Code/CI where needed;
  integrate isolated worktree commits and verify actual Functions HTTP settlement.
- [ ] Combined validation and persistence: all applicable checks, real Redis/Azurite tests,
  package/frontend builds, clean worktree excluding pre-existing `.github/skills/`.
  No live Azure deployment or availability certification is implied.

## References

- https://learn.microsoft.com/azure/foundry/openai/how-to/responses
- https://learn.microsoft.com/rest/api/microsoft-foundry/azureopenai/responses
- https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
