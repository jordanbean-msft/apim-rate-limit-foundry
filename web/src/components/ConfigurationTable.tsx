import { Badge, Button } from '@fluentui/react-components';
import type {
  Assignment,
  Budget,
  EditableCollection,
  EditableRecord,
  Organization,
  Price,
} from '../contracts';
import { microUsd } from '../format';

function RecordCells({
  collection,
  record,
  organizations,
}: {
  collection: EditableCollection;
  record: EditableRecord;
  organizations: Organization[];
}) {
  if (collection === 'budgets') {
    const budget = record as Budget;
    return (
      <>
        <td>
          <strong>{budget.name}</strong>
          <div className="fine-print">
            {budget.id} · {budget.tenant_id}
          </div>
        </td>
        <td>
          {budget.subject_type}
          <div className="fine-print">{budget.subject_id}</div>
        </td>
        <td>{budget.model}</td>
        <td>{microUsd(budget.limit_micro_usd)} / month</td>
        <td>
          <Badge appearance="tint" color={budget.enabled ? 'success' : 'subtle'}>
            {budget.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </td>
      </>
    );
  }
  if (collection === 'organizations') {
    const organization = record as Organization;
    const parent = organizations.find((item) => item.id === organization.department_id);
    return (
      <>
        <td>
          <strong>{organization.name}</strong>
          <div className="fine-print">{organization.id}</div>
        </td>
        <td>
          {organization.kind}
          <div className="fine-print">{parent ? `Department: ${parent.name}` : '—'}</div>
        </td>
        <td>{organization.business_unit}</td>
        <td>{organization.cost_center}</td>
        <td>
          <Badge appearance="tint" color={organization.enabled ? 'success' : 'subtle'}>
            {organization.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </td>
      </>
    );
  }
  if (collection === 'assignments') {
    const assignment = record as Assignment;
    return (
      <>
        <td>
          <strong>{assignment.display_label || assignment.principal_id}</strong>
          <div className="fine-print">
            {assignment.id} · principal {assignment.principal_id}
          </div>
        </td>
        <td>
          {assignment.team_id}
          <div className="fine-print">Department: {assignment.department_id}</div>
        </td>
        <td>{assignment.tenant_id}</td>
        <td>
          <Badge appearance="tint" color={assignment.enabled ? 'success' : 'subtle'}>
            {assignment.enabled ? 'Enabled' : 'Disabled'}
          </Badge>
        </td>
      </>
    );
  }
  const price = record as Price;
  return (
    <>
      <td>
        <strong>{price.model}</strong>
        <div className="fine-print">
          {price.id} · {price.version}
        </div>
      </td>
      <td>${price.input_per_million} / million</td>
      <td>${price.cached_input_per_million} / million</td>
      <td>${price.output_per_million} / million</td>
    </>
  );
}

export function ConfigurationTable({
  collection,
  records,
  organizations,
  admin,
  onEdit,
  onDelete,
}: {
  collection: EditableCollection;
  records: EditableRecord[];
  organizations: Organization[];
  admin: boolean;
  onEdit: (record: EditableRecord) => void;
  onDelete: (id: string) => void;
}) {
  const headings: Record<EditableCollection, string[]> = {
    budgets: ['Budget / tenant', 'Level / subject', 'Model', 'Monthly limit', 'Status'],
    organizations: ['Organization unit', 'Type / parent', 'Business unit', 'Cost center', 'Status'],
    assignments: ['User assignment', 'Team / department', 'Tenant', 'Status'],
    prices: ['Model / price version', 'Uncached input rate', 'Cached input rate', 'Output rate'],
  };
  return (
    <div className="table-scroll">
      <table>
        <caption className="visually-hidden">
          {collection === 'prices' ? 'OpenAI price catalog' : collection}
        </caption>
        <thead>
          <tr>
            {headings[collection].map((heading) => (
              <th key={heading}>{heading}</th>
            ))}
            {admin && <th>Actions</th>}
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <RecordCells collection={collection} record={record} organizations={organizations} />
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
      {collection === 'prices' && (
        <p className="fine-print panel-footnote">
          Price rates are exact decimal USD strings per million tokens, never micro-USD. The API
          pins the configured price version and computes cost using integer micro-USD. The portal
          does not reprice provider usage.
        </p>
      )}
    </div>
  );
}
