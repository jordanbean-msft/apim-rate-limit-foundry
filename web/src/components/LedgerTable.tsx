import { Badge } from '@fluentui/react-components';
import { isDenial, isEstimated } from '../accounting';
import type { LedgerRecord } from '../contracts';
import { microUsd, objectValue, services, text, utcTime } from '../format';
import { protocolLabel } from '../protocols';
import { UsageDetails } from './UsageDetails';

function AccountingDetails({ record }: { record: LedgerRecord }) {
  const request = objectValue(record.data.request);
  const usage = objectValue(record.data.usage || request.usage);
  const debits = Array.isArray(record.data.debits) ? record.data.debits.map(objectValue) : [];
  return (
    <>
      <Badge appearance="tint" color={isEstimated(record) ? 'warning' : 'success'}>
        {isEstimated(record)
          ? 'Estimated / conservative'
          : record.data.status === 'actual'
            ? 'Actual'
            : 'Recorded'}
      </Badge>
      {typeof record.data.cost_micro_usd === 'number' && (
        <div className="fine-print">
          Event cost: {microUsd(record.data.cost_micro_usd)} ({record.data.cost_micro_usd}{' '}
          microUSD).{' '}
          {isEstimated(record) ? 'Estimated / conservative cost.' : 'Recorded event cost.'}
        </div>
      )}
      {debits.length > 1 && (
        <div className="fine-print">
          Per-policy impacts below may repeat the same request cost. They are not additional
          charges; do not sum matching budget rules.
        </div>
      )}
      {debits.map((debit, index) => (
        <div className="fine-print" key={index}>
          {text(debit.policy_id)}:{' '}
          {debit.metric === 'cost'
            ? microUsd(debit.amount)
            : `${text(debit.amount)} ${text(debit.metric)}`}
          <br />
          {typeof debit.limit === 'number' && (
            <>
              Limit {debit.metric === 'cost' ? microUsd(debit.limit) : debit.limit.toLocaleString()}{' '}
              ·{' '}
            </>
          )}
          resets {utcTime(text(debit.reset_at, 'not reported'))}
        </div>
      ))}
      {record.data.remaining !== undefined && (
        <div className="fine-print">
          Last-decision remaining: {text(record.data.remaining)} (matched rule units; snapshot)
        </div>
      )}
      <UsageDetails
        usage={usage}
        anthropic={
          request.service === 'foundry' &&
          (record.data.api_protocol ?? request.api_protocol) === 'anthropic-messages'
        }
      />
      {record.data.cached_input_reported === false && (
        <div className="fine-print">
          Cache-read usage was not reported. Missing cache counters are not assumed to be zero.
        </div>
      )}
      {record.data.cache_write_input_reported === false && (
        <div className="fine-print">
          Cache-write usage was not reported. Missing cache counters are not assumed to be zero.
        </div>
      )}
      {record.data.reason !== undefined && (
        <div className="fine-print">{text(record.data.reason)}</div>
      )}
    </>
  );
}

export function LedgerTable({ records, mode }: { records: LedgerRecord[]; mode: string }) {
  const audit = mode === 'audit';
  return (
    <div className="table-scroll">
      <table>
        <caption className="visually-hidden">
          {audit ? 'Audit events' : 'Usage and reconciliation events'}
        </caption>
        <thead>
          <tr>
            <th>Event / UTC time</th>
            <th>{audit ? 'Action' : 'Service / status'}</th>
            <th>{audit ? 'Actor / target' : 'Accounting'}</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => {
            const request = objectValue(record.data.request);
            const service = request.service as keyof typeof services;
            const protocol = protocolLabel({
              ...request,
              api_protocol: record.data.api_protocol ?? request.api_protocol,
            });
            return (
              <tr key={record.id}>
                <td>
                  <strong>{record.kind}</strong>
                  <div className="fine-print">{utcTime(record.timestamp)}</div>
                  <div className="fine-print">{record.id}</div>
                </td>
                <td>
                  {audit
                    ? text(record.data.action)
                    : services[service] || text(record.data.status, record.kind)}
                  <div className="fine-print">
                    {text(request.model, record.subscription_id || 'Application subscription')}
                  </div>
                  {!audit && protocol && <div className="fine-print">{protocol}</div>}
                  {isDenial(record) && (
                    <Badge appearance="tint" color="danger">
                      Denied · no debit
                    </Badge>
                  )}
                </td>
                <td>
                  {audit ? (
                    <>
                      {text(record.data.actor_id, record.principal_id)}
                      <div className="fine-print">
                        {text(record.data.collection, '')} {text(record.data.record_id, '')}
                      </div>
                    </>
                  ) : (
                    <AccountingDetails record={record} />
                  )}
                </td>
                <td>
                  <details>
                    <summary>Inspect event</summary>
                    <pre>{JSON.stringify(record, null, 2)}</pre>
                  </details>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
