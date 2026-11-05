import type { ApiProtocol } from './contracts';
import { text } from './format';

const protocols: Record<ApiProtocol, string> = {
  'openai-chat': 'OpenAI Chat Completions',
  'openai-responses': 'OpenAI Responses',
  'anthropic-messages': 'Anthropic Messages',
};

export function protocolLabel(request: Record<string, unknown>): string | null {
  if (request.service !== 'foundry') return null;
  if (request.api_protocol === undefined || request.api_protocol === null) {
    return 'OpenAI Chat Completions (legacy default)';
  }
  const protocol = text(request.api_protocol, '');
  return Object.hasOwn(protocols, protocol)
    ? protocols[protocol as ApiProtocol]
    : `Unrecognized protocol: ${protocol || 'invalid metadata'}`;
}
