import {
  Badge,
  Table,
  TableBody,
  TableCell,
  TableCellLayout,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';
import type { UsageRecord } from '../contracts';
import { microUsd, utcTime } from '../format';

/** Display persisted authorized events with explicit unknown outcomes; never reprice provider usage. */
export function UsageTable({ records }: { records: UsageRecord[] }) {
  if (!records.length)
    return <p className="empty-inline">No authorized usage records are available.</p>;
  return (
    <div className="table-scroll">
      <Table aria-label="Authorized OpenAI usage records">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>Time (UTC)</TableHeaderCell>
            <TableHeaderCell>Model</TableHeaderCell>
            <TableHeaderCell>Team / department</TableHeaderCell>
            <TableHeaderCell className="num">Input · cached · output tokens</TableHeaderCell>
            <TableHeaderCell className="num">Actual cost</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => (
            <TableRow key={record.event_id}>
              <TableCell>
                <TableCellLayout appearance="primary" description={record.request_id}>
                  {utcTime(record.timestamp)}
                </TableCellLayout>
              </TableCell>
              <TableCell>
                <TableCellLayout
                  description={`${record.api_protocol}${record.streaming ? ' · streaming' : ''}`}
                >
                  {record.model}
                </TableCellLayout>
              </TableCell>
              <TableCell>
                <TableCellLayout
                  description={`${record.department_id} · ${record.subscription_id}`}
                >
                  {record.team_id}
                </TableCellLayout>
              </TableCell>
              <TableCell className="num">
                {record.status === 'actual'
                  ? `${record.input_tokens?.toLocaleString()} · ${record.cached_input_tokens?.toLocaleString()} · ${record.output_tokens?.toLocaleString()}`
                  : 'Unknown'}
              </TableCell>
              <TableCell className="num">
                {record.status === 'actual' && record.cost_micro_usd !== null ? (
                  microUsd(record.cost_micro_usd)
                ) : (
                  <>
                    <Badge appearance="tint" color="warning">
                      Usage unknown
                    </Badge>
                    <div className="secondary">
                      {record.cost_micro_usd === null
                        ? 'Not charged as zero'
                        : `${microUsd(record.cost_micro_usd)} estimated upper bound`}
                    </div>
                  </>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
