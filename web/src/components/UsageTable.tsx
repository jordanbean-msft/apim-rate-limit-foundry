import { Badge } from '@fluentui/react-components';
import type { UsageRecord } from '../contracts';
import { microUsd, utcTime } from '../format';

export function UsageTable({ records }: { records: UsageRecord[] }) {
  if (!records.length)
    return <p className="empty-inline">No authorized usage records are available.</p>;
  return (
    <div className="table-scroll">
      <table>
        <caption className="visually-hidden">Authorized OpenAI usage records</caption>
        <thead>
          <tr>
            <th>Time / request</th>
            <th>Model / protocol</th>
            <th>Organization</th>
            <th>Tokens: input · cached · output</th>
            <th>Actual cost</th>
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.event_id}>
              <td>
                <strong>{utcTime(record.timestamp)}</strong>
                <div className="fine-print">{record.request_id}</div>
                <Badge appearance="tint" color={record.streaming ? 'informative' : 'subtle'}>
                  {record.streaming ? 'Streaming' : 'Non-streaming'}
                </Badge>
              </td>
              <td>
                <strong>{record.model}</strong>
                <div className="fine-print">{record.api_protocol}</div>
                <div className="fine-print">Price version {record.price_version}</div>
              </td>
              <td>
                {record.business_unit} · {record.cost_center}
                <div className="fine-print">
                  Department {record.department_id} · Team {record.team_id}
                </div>
                <div className="fine-print">Application {record.subscription_id}</div>
              </td>
              <td>
                {record.status === 'actual'
                  ? `${record.input_tokens?.toLocaleString()} · ${record.cached_input_tokens?.toLocaleString()} · ${record.output_tokens?.toLocaleString()}`
                  : 'Unknown'}
              </td>
              <td>
                {record.status === 'actual' && record.cost_micro_usd !== null ? (
                  <>
                    {microUsd(record.cost_micro_usd)}
                    <div className="fine-print">Finalized actual</div>
                  </>
                ) : (
                  <>
                    <Badge appearance="tint" color="warning">
                      Usage unknown
                    </Badge>
                    <div className="fine-print">Not charged as zero</div>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
