import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  Select,
  Spinner,
  useRestoreFocusTarget,
} from '@fluentui/react-components';
import {
  ArrowClockwiseRegular,
  ArrowExitRegular,
  DataTrendingRegular,
  GridRegular,
  HistoryRegular,
  ReceiptMoneyRegular,
  ShieldCheckmarkRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { isDenial } from './accounting';
import { ConfigurationTable } from './components/ConfigurationTable';
import { Dashboard } from './components/Dashboard';
import { CallerReport } from './components/CallerReport';
import { LedgerTable } from './components/LedgerTable';
import { ModelInventory } from './components/ModelInventory';
import { Overview } from './components/Overview';
import type {
  Collection,
  Collections,
  EditableCollection,
  EditableRecord,
  LedgerRecord,
  PortalApi,
  Role,
} from './contracts';
import { objectValue, services, utcTime } from './format';
import { RecordEditor } from './RecordEditor';
import { track } from './telemetry';

type Page = 'overview' | Collection | 'denials' | 'callers' | 'dashboard';
type Data = { [K in Collection]: Collections[K][] };
const emptyData: Data = {
  models: [],
  subscriptions: [],
  policies: [],
  prices: [],
  assignments: [],
  usage: [],
  audit: [],
  reconciliation: [],
};
const collections: Collection[] = [
  'models',
  'subscriptions',
  'policies',
  'prices',
  'assignments',
  'usage',
  'audit',
  'reconciliation',
];
const pages = [
  { id: 'overview', label: 'Overview', icon: <GridRegular /> },
  { id: 'dashboard', label: 'Azure dashboard', icon: <DataTrendingRegular /> },
  { id: 'usage', label: 'Service usage', icon: <DataTrendingRegular /> },
  { id: 'denials', label: 'Limit violations', icon: <WarningRegular /> },
  { id: 'callers', label: 'Application subscription spend & denials', icon: <GridRegular /> },
  { id: 'reconciliation', label: 'Reconciliation', icon: <ArrowClockwiseRegular /> },
  { id: 'policies', label: 'Budget policies', icon: <ShieldCheckmarkRegular /> },
  { id: 'assignments', label: 'Assignments', icon: <GridRegular /> },
  { id: 'prices', label: 'Price catalog', icon: <ReceiptMoneyRegular /> },
  { id: 'models', label: 'Model inventory', icon: <GridRegular /> },
  { id: 'subscriptions', label: 'Application subscriptions', icon: <GridRegular /> },
  { id: 'audit', label: 'Audit history', icon: <HistoryRegular /> },
] as const;
const descriptions: Record<Page, string> = {
  overview: 'A clear view of your AI service limits and accounting activity.',
  dashboard: 'Charts and tables from the deployed Azure dashboard, using its configured queries.',
  policies: 'Service-aware limits with UTC calendar periods and explicit accounting units.',
  prices: 'Versioned decimal USD prices. Separate input, output, cached input, and service units.',
  models: 'Read-only deployed model aliases, provider deployments, limits and pinned prices.',
  assignments:
    'Bind tenant-scoped application subscriptions to policies and assign explicit data readers.',
  usage: 'Server-scoped usage events. Estimated reservations are not actual invoices.',
  denials: 'Requests denied by a budget or unit limit. Denials do not debit budgets.',
  reconciliation: 'Track conservative streaming reservations and trusted actual usage.',
  audit: 'Read-only configuration and decision history, scoped by API authorization.',
  subscriptions: 'Read-only application subscriptions registered for this tenant.',
  callers:
    'Application-subscription denials, dashboard correlation and effective spend by service and model.',
};
const editable = (page: Page): page is EditableCollection =>
  ['policies', 'prices', 'assignments'].includes(page);

function RecordBrowser({
  page,
  records,
  error,
  loading,
  admin,
  subscriptions,
  onEdit,
  onDelete,
}: {
  page: Exclude<Page, 'overview' | 'callers' | 'models'>;
  records: Collections[Collection][];
  error?: string;
  loading: boolean;
  admin: boolean;
  subscriptions: Collections['subscriptions'][];
  onEdit: (collection: EditableCollection, record: EditableRecord) => void;
  onDelete: (collection: EditableCollection, id: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [serviceFilter, setServiceFilter] = useState('all');
  const [subscriptionFilter, setSubscriptionFilter] = useState('all');
  const filtered = records.filter((record) => {
    const request = 'data' in record ? objectValue(record.data.request) : {};
    const service = 'service' in record ? record.service : request.service;
    return (
      JSON.stringify(record).toLowerCase().includes(search.toLowerCase()) &&
      (serviceFilter === 'all' || service === serviceFilter) &&
      (!('subscription_id' in record) ||
        subscriptionFilter === 'all' ||
        record.subscription_id === subscriptionFilter)
    );
  });
  return (
    <section className="surface data-panel">
      <div className="table-toolbar">
        <Input
          aria-label="Search records"
          placeholder="Search these records…"
          value={search}
          onChange={(_, value) => setSearch(value.value)}
        />
        {['policies', 'prices', 'usage', 'denials'].includes(page) && (
          <Select
            aria-label="Filter by service"
            value={serviceFilter}
            onChange={(_, value) => setServiceFilter(value.value)}
          >
            <option value="all">All services</option>
            {Object.entries(services).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </Select>
        )}
        {['policies', 'assignments'].includes(page) && (
          <Select
            aria-label="Filter by application subscription"
            value={subscriptionFilter}
            onChange={(_, value) => setSubscriptionFilter(value.value)}
          >
            <option value="all">All application subscriptions</option>
            {page === 'policies' && <option value="*">Shared policy templates</option>}
            {subscriptions.map((subscription) => (
              <option value={subscription.id} key={subscription.id}>
                {subscription.display_name} · {subscription.id}
              </option>
            ))}
          </Select>
        )}
        <span className="muted">{filtered.length} records</span>
      </div>
      {error ? (
        <p className="empty-inline">This collection is unavailable. Use Refresh to retry.</p>
      ) : page === 'subscriptions' ? (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">Registered application subscriptions</caption>
            <thead>
              <tr>
                <th>Application subscription</th>
                <th>Subscription ID</th>
                <th>Tenant ID</th>
              </tr>
            </thead>
            <tbody>
              {(filtered as Collections['subscriptions'][]).map((subscription) => (
                <tr key={subscription.id}>
                  <td>{subscription.display_name}</td>
                  <td>
                    <code>{subscription.id}</code>
                  </td>
                  <td>
                    <code>{subscription.tenant_id}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : editable(page) ? (
        <ConfigurationTable
          collection={page}
          records={filtered as EditableRecord[]}
          subscriptions={subscriptions}
          admin={admin}
          onEdit={(record) => onEdit(page, record)}
          onDelete={(id) => onDelete(page, id)}
        />
      ) : (
        <LedgerTable records={filtered as LedgerRecord[]} mode={page} />
      )}
      {!filtered.length && !loading && !error && (
        <div className="empty-state">
          <DataTrendingRegular />
          <h3>No matching records</h3>
          <p>Try a different filter, refresh, or wait for authorized activity.</p>
        </div>
      )}
    </section>
  );
}

export function Portal({
  api,
  roles,
  identity,
  cloud,
  demo = false,
  profileGreeting,
  onSignOut,
}: {
  api: PortalApi;
  roles: Role[];
  identity: string;
  cloud: string;
  demo?: boolean;
  profileGreeting?: React.ReactNode;
  onSignOut?: () => void;
}) {
  const [page, setPage] = useState<Page>('overview');
  const [data, setData] = useState<Data>(emptyData);
  const [errors, setErrors] = useState<Partial<Record<Collection, string>>>({});
  const [loading, setLoading] = useState(false);
  const [loadedAt, setLoadedAt] = useState('');
  const [editor, setEditor] = useState<{
    collection: EditableCollection;
    record?: EditableRecord;
  } | null>(null);
  const [deleting, setDeleting] = useState<{ collection: EditableCollection; id: string } | null>(
    null,
  );
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [mutationError, setMutationError] = useState('');
  const [notice, setNotice] = useState('');
  const sequence = useRef(0);
  const restoreFocusTarget = useRestoreFocusTarget();
  const admin = roles.includes('RateLimit.Admin');
  const canRead = admin || roles.includes('RateLimit.Reader');

  useEffect(() => {
    track('portal_page', { page, outcome: 'success' });
  }, [page]);

  const refresh = useCallback(async () => {
    if (!canRead) return;
    const start = performance.now();
    const requestId = ++sequence.current;
    setLoading(true);
    const results = await Promise.allSettled(collections.map((collection) => api.list(collection)));
    const failureCount = results.filter((result) => result.status === 'rejected').length;
    track(
      'portal_refresh',
      { outcome: failureCount ? 'partial_failure' : 'success' },
      { collectionCount: collections.length, failureCount, durationMs: performance.now() - start },
    );
    if (requestId !== sequence.current) return;
    const next = { ...emptyData };
    const failures: Partial<Record<Collection, string>> = {};
    results.forEach((result, index) => {
      const key = collections[index];
      if (result.status === 'fulfilled') (next[key] as unknown[]) = result.value;
      else
        failures[key] =
          result.reason instanceof Error ? result.reason.message : 'Unable to load records.';
    });
    setData(next);
    setErrors(failures);
    setLoadedAt(new Date().toISOString());
    setLoading(false);
  }, [api, canRead]);

  const invalidate = useCallback(() => {
    sequence.current++;
  }, []);
  useEffect(() => {
    void refresh();
    return invalidate;
  }, [refresh, invalidate]);

  async function save(record: EditableRecord) {
    if (!admin || !editor) throw new Error('Administrator access is required.');
    if (!editor.record && data[editor.collection].some((existing) => existing.id === record.id)) {
      throw new Error('This ID already exists. Edit the existing record or choose a new ID.');
    }
    await api.save(editor.collection, record);
    setNotice('Changes saved. The API remains the source of truth.');
    await refresh();
  }
  async function confirmDelete() {
    if (!admin || !deleting) return;
    setDeleteBusy(true);
    setMutationError('');
    try {
      await api.remove(deleting.collection, deleting.id);
      track('portal_configuration', {
        collection: deleting.collection,
        action: 'delete',
        outcome: 'success',
        errorCategory: 'none',
      });
      setDeleting(null);
      setNotice('Record deleted.');
      await refresh();
    } catch (cause) {
      track('portal_configuration', {
        collection: deleting.collection,
        action: 'delete',
        outcome: 'failure',
        errorCategory: 'api',
      });
      setMutationError(cause instanceof Error ? cause.message : 'Delete failed.');
    } finally {
      setDeleteBusy(false);
    }
  }
  function cancelDelete() {
    if (!deleting || deleteBusy) return;
    track('portal_configuration', {
      collection: deleting.collection,
      action: 'delete',
      outcome: 'cancelled',
      errorCategory: 'none',
    });
    setDeleting(null);
  }
  const currentCollection =
    page === 'denials'
      ? 'usage'
      : page === 'overview' || page === 'callers' || page === 'dashboard'
        ? null
        : page;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#main" onClick={() => setPage('overview')}>
          <span className="brand-mark">
            <ShieldCheckmarkRegular />
          </span>
          <span>
            AI Budget<span className="brand-sub">CONTROL PLANE</span>
          </span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav aria-label="Primary navigation">
          {pages
            .filter((item) => item.id !== 'dashboard' || admin)
            .map((item) => (
              <button
                key={item.id}
                className={`nav-item ${page === item.id ? 'active' : ''}`}
                aria-current={page === item.id ? 'page' : undefined}
                onClick={() => {
                  setPage(item.id);
                  setNotice('');
                }}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="status-dot" />
          {cloud === 'government' ? 'Azure Government' : 'Azure Commercial'}
          <p>
            {demo ? 'Local fixture mode · no authentication' : 'Tenant-scoped · Entra protected'}
          </p>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="breadcrumb">
            AI gateway <span>/</span> {pages.find((item) => item.id === page)?.label}
          </span>
          <div className="account">
            <Badge appearance="tint" color={admin ? 'brand' : 'informative'}>
              {admin ? 'Administrator' : canRead ? 'Reader' : 'Unassigned'}
            </Badge>
            {profileGreeting ?? <span className="profile-greeting">Howdy {identity}!</span>}
            {onSignOut && (
              <Button
                icon={<ArrowExitRegular />}
                appearance="subtle"
                onClick={onSignOut}
                aria-label="Sign out"
              />
            )}
          </div>
        </header>
        <main id="main" tabIndex={-1} {...restoreFocusTarget}>
          {demo && (
            <MessageBar intent="warning">
              <MessageBarBody>
                <strong>LOCAL DEMO — fixture data only.</strong> No authentication or Azure calls.
                Edits live only in this browser session and reset on reload. Prices are
                illustrative, not Azure quotes.
              </MessageBarBody>
            </MessageBar>
          )}
          {!canRead ? (
            <section className="surface empty-state">
              <ShieldCheckmarkRegular />
              <h1>Access not assigned</h1>
              <p role="alert">
                Your API access token does not contain RateLimit.Reader or RateLimit.Admin. Ask your
                administrator for a portal role. Gateway identities cannot use this portal.
              </p>
            </section>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    {admin ? 'GOVERNANCE & VISIBILITY' : 'YOUR USAGE & LIMITS'}
                  </div>
                  <h1>{pages.find((item) => item.id === page)?.label}</h1>
                  <p>{descriptions[page]}</p>
                </div>
                {page !== 'dashboard' && (
                  <div className="heading-actions">
                    <Button
                      icon={<ArrowClockwiseRegular />}
                      disabled={loading}
                      onClick={() => {
                        void refresh();
                      }}
                    >
                      Refresh
                    </Button>
                    {admin && editable(page) && (
                      <Button
                        appearance="primary"
                        disabled={loading}
                        onClick={() => setEditor({ collection: page })}
                      >
                        Create{' '}
                        {page === 'prices'
                          ? 'price version'
                          : page === 'policies'
                            ? 'policy'
                            : 'assignment'}
                      </Button>
                    )}
                  </div>
                )}
              </div>
              {!admin && (
                <div className="read-only-note">
                  <ShieldCheckmarkRegular /> Read-only workspace. The API scopes records to your
                  tenant and assigned application subscriptions.
                </div>
              )}
              {Object.entries(errors).map(([collection, message]) => (
                <MessageBar key={collection} intent="error">
                  <MessageBarBody>
                    <strong>{collection}:</strong> {message} Use Refresh to retry. No sample data
                    has been substituted.
                  </MessageBarBody>
                </MessageBar>
              ))}
              {notice && (
                <MessageBar intent="success">
                  <MessageBarBody>{notice}</MessageBarBody>
                </MessageBar>
              )}
              {loading && (
                <div role="status" className="loading-line">
                  <Spinner size="tiny" label="Loading authorized records…" />
                </div>
              )}
              {page === 'dashboard' && !admin ? (
                <section className="surface empty-state" aria-label="Dashboard access denied">
                  <ShieldCheckmarkRegular />
                  <h2>Administrator access required</h2>
                  <p role="alert">
                    The Azure dashboard includes workspace-wide telemetry and is available only to
                    RateLimit.Admin. No dashboard request was made.
                  </p>
                </section>
              ) : page === 'dashboard' ? (
                <Dashboard api={api} fixtureMode={demo} />
              ) : page === 'overview' ? (
                <Overview
                  policies={data.policies}
                  usage={data.usage}
                  subscriptions={data.subscriptions}
                  errors={errors}
                  loading={loading}
                  navigate={setPage}
                />
              ) : page === 'callers' ? (
                <CallerReport
                  api={api}
                  refreshKey={loadedAt}
                  policies={data.policies}
                  subscriptions={data.subscriptions}
                />
              ) : page === 'models' ? (
                <ModelInventory
                  models={data.models}
                  prices={data.prices}
                  modelsError={errors.models}
                  pricesError={errors.prices}
                  loading={loading}
                />
              ) : (
                <RecordBrowser
                  key={page}
                  page={page}
                  records={page === 'denials' ? data.usage.filter(isDenial) : data[page]}
                  error={currentCollection ? errors[currentCollection] : undefined}
                  loading={loading}
                  admin={admin}
                  subscriptions={data.subscriptions}
                  onEdit={(collection, record) => setEditor({ collection, record })}
                  onDelete={(collection, id) => {
                    setMutationError('');
                    setDeleting({ collection, id });
                  }}
                />
              )}
              <footer className="page-footer">
                <span>
                  {loadedAt
                    ? `Last refresh attempt ${utcTime(loadedAt)}`
                    : 'Awaiting first refresh'}
                </span>
                <span>USD · UTC periods · API-enforced subscription scope</span>
              </footer>
            </>
          )}
        </main>
      </div>
      {editor && admin && (
        <RecordEditor
          collection={editor.collection}
          record={editor.record}
          policies={data.policies}
          models={data.models}
          onSave={save}
          onClose={() => setEditor(null)}
        />
      )}
      {deleting && admin && (
        <Dialog
          open
          onOpenChange={(_, value) => {
            if (!value.open) cancelDelete();
          }}
        >
          <DialogSurface>
            <DialogBody>
              <DialogTitle>Delete this record?</DialogTitle>
              <DialogContent>
                <p>
                  <strong>{deleting.id}</strong> will be removed from {deleting.collection}. This
                  cannot be undone. Existing history is not deleted. Referenced records may be
                  rejected by the API.
                </p>
                {mutationError && (
                  <p role="alert" className="error">
                    {mutationError}
                  </p>
                )}
              </DialogContent>
              <div className="dialog-actions">
                <Button disabled={deleteBusy} onClick={cancelDelete}>
                  Cancel
                </Button>
                <Button
                  appearance="primary"
                  disabled={deleteBusy}
                  onClick={() => {
                    void confirmDelete();
                  }}
                >
                  {deleteBusy ? 'Deleting…' : 'Confirm delete'}
                </Button>
              </div>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      )}
    </div>
  );
}
