import { Badge, Button } from '@fluentui/react-components';
import type { Assignment, EditableCollection, EditableRecord, Policy, Price } from '../contracts';
import { services } from '../format';
import { PolicyLimit } from './PolicyLimit';

function PriceDetails({ price }: { price: Price }) {
  const summary =
    price.service === 'foundry'
      ? `Input $${price.input_per_million} · Output $${price.output_per_million} · Cached $${price.cached_input_per_million} / million tokens`
      : price.service === 'document-intelligence'
        ? `$${price.per_page} / page · $${price.per_request} / request`
        : `$${price.per_text_record} / text record · $${price.per_request} / request`;
  return (
    <>
      <div className="price-summary">{summary}</div>
      <details>
        <summary>All accounting dimensions</summary>
        <dl className="price-dimensions">
          <dt>Input / million tokens</dt>
          <dd>${price.input_per_million}</dd>
          <dt>Output / million tokens</dt>
          <dd>${price.output_per_million}</dd>
          <dt>Cached input / million tokens</dt>
          <dd>${price.cached_input_per_million}</dd>
          <dt>Per page</dt>
          <dd>${price.per_page}</dd>
          <dt>Per text record</dt>
          <dd>${price.per_text_record}</dd>
          <dt>Per request</dt>
          <dd>${price.per_request}</dd>
        </dl>
      </details>
    </>
  );
}

function RecordCells({
  collection,
  record,
}: {
  collection: EditableCollection;
  record: EditableRecord;
}) {
  if (collection === 'policies') {
    const policy = record as Policy;
    return (
      <>
        <td>
          <strong>{policy.name}</strong>
          <div className="fine-print">
            {policy.id} · priority {policy.priority}
          </div>
          <div className="fine-print">
            Tenant {policy.tenant_id || '*'} · principal {policy.principal_id}
          </div>
        </td>
        <td>
          {services[policy.service]}
          <div className="fine-print">{policy.model}</div>
        </td>
        <td>
          <PolicyLimit policy={policy} />
        </td>
        <td>
          <Badge appearance="tint" color={policy.enabled ? 'success' : 'subtle'}>
            {policy.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </td>
      </>
    );
  }
  if (collection === 'prices') {
    const price = record as Price;
    return (
      <>
        <td>
          <strong>{price.model}</strong>
          <div className="fine-print">
            {price.version} · {price.id}
          </div>
        </td>
        <td>{services[price.service]}</td>
        <td>
          <PriceDetails price={price} />
        </td>
      </>
    );
  }
  const assignment = record as Assignment;
  return (
    <>
      <td>
        <strong>{assignment.id}</strong>
      </td>
      <td>
        {assignment.tenant_id}
        <div className="fine-print">{assignment.principal_id}</div>
      </td>
      <td>{assignment.policy_ids.join(', ')}</td>
    </>
  );
}

export function ConfigurationTable({
  collection,
  records,
  admin,
  onEdit,
  onDelete,
}: {
  collection: EditableCollection;
  records: EditableRecord[];
  admin: boolean;
  onEdit: (record: EditableRecord) => void;
  onDelete: (id: string) => void;
}) {
  const headings = {
    policies: ['Policy / scope', 'Service / model', 'Limit', 'Status'],
    prices: ['Model / version', 'Service', 'USD rates'],
    assignments: ['Assignment', 'Tenant / principal', 'Policy IDs'],
  };
  return (
    <>
      <div className="table-scroll">
        <table>
          <caption className="visually-hidden">
            {collection === 'prices' ? 'Versioned price catalog' : collection}
          </caption>
          <thead>
            <tr>
              {headings[collection].map((label) => (
                <th key={label}>{label}</th>
              ))}
              {admin && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                <RecordCells collection={collection} record={record} />
                {admin && (
                  <td>
                    <div className="row-actions">
                      <Button
                        size="small"
                        onClick={() => onEdit(record)}
                        aria-label={`Edit ${record.id}`}
                      >
                        Edit
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        onClick={() => onDelete(record.id)}
                        aria-label={`Delete ${record.id}`}
                      >
                        Delete
                      </Button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {collection === 'prices' && (
        <p className="fine-print panel-footnote">
          Exact decimal USD strings, not microUSD. Cached input replaces uncached pricing for
          reported cache-hit tokens. The catalog is administrator-managed, not a live retail feed.
          When multiple versions exist for a service/model, the gateway must pin an explicit
          price_version or requests fail closed.
        </p>
      )}
    </>
  );
}
