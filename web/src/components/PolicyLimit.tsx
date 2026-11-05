import type { Policy } from '../contracts';
import { microUsd } from '../format';

export function PolicyLimit({ policy }: { policy: Policy }) {
  return (
    <>
      <strong>
        {policy.metric === 'cost' ? microUsd(policy.limit) : policy.limit.toLocaleString()}
      </strong>
      <span className="muted"> / {policy.period}</span>
      <div className="fine-print">
        {policy.metric === 'cost' ? `${policy.limit} microUSD` : policy.metric.replace('_', ' ')} ·
        UTC
      </div>
    </>
  );
}
