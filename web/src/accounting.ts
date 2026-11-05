import type { LedgerRecord } from './contracts';

export function isDenial(record: LedgerRecord): boolean {
  return (
    record.kind.includes('deni') || record.data.allowed === false || record.data.status === 'denied'
  );
}

export function isEstimated(record: LedgerRecord): boolean {
  return record.data.estimated === true || record.data.status === 'conservative';
}
