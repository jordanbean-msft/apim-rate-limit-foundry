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
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowClockwiseRegular,
  ArrowExitRegular,
  DataTrendingRegular,
  GridRegular,
  ReceiptMoneyRegular,
  ShieldCheckmarkRegular,
} from '@fluentui/react-icons';
import { BudgetStatusTable } from './components/BudgetStatusTable';
import { ChargebackReport } from './components/ChargebackReport';
import { ConfigurationTable } from './components/ConfigurationTable';
import { Dashboard } from './components/Dashboard';
import { ModelInventory } from './components/ModelInventory';
import { Overview } from './components/Overview';
import { UsageTable } from './components/UsageTable';
import type {
  BudgetStatus,
  Collection,
  Collections,
  EditableCollection,
  EditableRecord,
  Organization,
  PortalApi,
  Role,
} from './contracts';
import { utcTime } from './format';
import { RecordEditor } from './RecordEditor';
import { track } from './telemetry';

type Page =
  | 'overview'
  | 'budgets'
  | 'organizations'
  | 'assignments'
  | 'prices'
  | 'models'
  | 'usage'
  | 'chargeback'
  | 'dashboard';
type Data = { [K in Collection]: Collections[K][] };
type Errors = Partial<Record<Collection | 'budgetStatus' | 'chargeback', string>>;
const emptyData: Data = {
  budgets: [],
  organizations: [],
  assignments: [],
  prices: [],
  models: [],
  usage: [],
};
const editablePages: EditableCollection[] = ['budgets', 'organizations', 'assignments', 'prices'];
const pages: { id: Page; label: string; icon: React.ReactNode; adminOnly?: boolean }[] = [
  { id: 'overview', label: 'Overview', icon: <GridRegular /> },
  { id: 'budgets', label: 'Monthly budgets', icon: <ShieldCheckmarkRegular /> },
  { id: 'chargeback', label: 'Chargeback', icon: <ReceiptMoneyRegular /> },
  { id: 'usage', label: 'Usage records', icon: <DataTrendingRegular /> },
  { id: 'organizations', label: 'Organization units', icon: <GridRegular />, adminOnly: true },
  { id: 'assignments', label: 'User assignments', icon: <GridRegular />, adminOnly: true },
  { id: 'prices', label: 'OpenAI price cards', icon: <ReceiptMoneyRegular />, adminOnly: true },
  { id: 'models', label: 'Model inventory', icon: <GridRegular /> },
  { id: 'dashboard', label: 'Azure dashboard', icon: <DataTrendingRegular />, adminOnly: true },
];
const descriptions: Record<Page, string> = {
  overview: 'Monthly USD budgets, actual spend and authorized OpenAI usage.',
  budgets: 'Monthly UTC calendar limits apply to all configured user, team and department levels.',
  organizations:
    'Manage departments, teams, parent relationships, business units and cost centers.',
  assignments:
    'Explicitly assign Entra principals to a team and department; membership is managed here.',
  prices: 'Versioned OpenAI input, cached-input and output rates as exact decimal USD strings.',
  models: 'Read-only aliases, OpenAI protocol, provider deployment and pinned price version.',
  usage: 'Provider-reported actual usage and explicit unknown-stream outcomes.',
  chargeback:
    'Authorized monthly chargeback grouped by business unit, cost center and usage dimensions.',
  dashboard: 'Charts and tables from the deployed Azure dashboard using its shared query catalog.',
};

function isEditable(page: Page): page is EditableCollection {
  return editablePages.includes(page as EditableCollection);
}

function collectionLabel(collection: EditableCollection): string {
  return {
    budgets: 'budget',
    organizations: 'organization unit',
    assignments: 'user assignment',
    prices: 'OpenAI price card',
  }[collection];
}

function RecordBrowser({
  collection,
  records,
  organizations,
  admin,
  loading,
  onEdit,
  onDelete,
}: {
  collection: EditableCollection;
  records: EditableRecord[];
  organizations: Organization[];
  admin: boolean;
  loading: boolean;
  onEdit: (record: EditableRecord) => void;
  onDelete: (id: string) => void;
}) {
  const [search, setSearch] = useState('');
  const filtered = records.filter((record) =>
    JSON.stringify(record).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <section className="surface data-panel">
      <div className="table-toolbar">
        <Input
          aria-label={`Search ${collection}`}
          placeholder={`Search ${collection}…`}
          value={search}
          onChange={(_, data) => setSearch(data.value)}
        />
        <span className="muted">{filtered.length} records</span>
      </div>
      <ConfigurationTable
        collection={collection}
        records={filtered}
        organizations={organizations}
        admin={admin}
        onEdit={onEdit}
        onDelete={onDelete}
      />
      {!filtered.length && !loading && (
        <div className="empty-state">
          <DataTrendingRegular />
          <h3>No matching records</h3>
          <p>Refresh or create a new {collectionLabel(collection)}.</p>
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
  const [status, setStatus] = useState<BudgetStatus[]>([]);
  const [errors, setErrors] = useState<Errors>({});
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
    const tasks: {
      key: Collection | 'budgetStatus';
      run: () => Promise<unknown>;
    }[] = [
      { key: 'models', run: () => api.list('models') },
      { key: 'usage', run: () => api.list('usage') },
      { key: 'budgetStatus', run: () => api.budgetStatus() },
    ];
    if (admin) {
      tasks.push(
        { key: 'budgets', run: () => api.list('budgets') },
        { key: 'organizations', run: () => api.list('organizations') },
        { key: 'assignments', run: () => api.list('assignments') },
        { key: 'prices', run: () => api.list('prices') },
      );
    }
    const results = await Promise.allSettled(tasks.map((task) => task.run()));
    const failureCount = results.filter((result) => result.status === 'rejected').length;
    track(
      'portal_refresh',
      { outcome: failureCount ? 'partial_failure' : 'success' },
      { collectionCount: tasks.length, failureCount, durationMs: performance.now() - start },
    );
    if (requestId !== sequence.current) return;
    const next = { ...emptyData };
    const failures: Errors = {};
    let nextStatus: BudgetStatus[] = [];
    results.forEach((result, index) => {
      const key = tasks[index].key;
      if (result.status === 'fulfilled') {
        if (key === 'budgetStatus') nextStatus = result.value as BudgetStatus[];
        else (next[key] as unknown[]) = result.value as unknown[];
      } else {
        failures[key] =
          result.reason instanceof Error ? result.reason.message : 'Unable to load records.';
      }
    });
    setData(next);
    setStatus(nextStatus);
    setErrors(failures);
    setLoadedAt(new Date().toISOString());
    setLoading(false);
  }, [api, canRead, admin]);

  useEffect(() => {
    void refresh();
    const activeSequence = sequence;
    return () => {
      activeSequence.current++;
    };
  }, [refresh]);

  async function save(record: EditableRecord) {
    if (!admin || !editor) throw new Error('Administrator access is required.');
    if (
      !editor.record &&
      (data[editor.collection] as { id: string }[]).some((existing) => existing.id === record.id)
    )
      throw new Error('This ID already exists. Edit the existing record or choose a new ID.');
    await api.save(editor.collection, record as never);
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
            .filter((item) => !item.adminOnly || admin)
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
            <Badge appearance="tint" color={admin ? 'brand' : canRead ? 'informative' : 'subtle'}>
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
        <main id="main" tabIndex={-1}>
          {demo && (
            <MessageBar intent="warning">
              <MessageBarBody>
                <strong>LOCAL DEMO — fixture data only.</strong> No authentication or Azure calls.
                Edits live only in this browser session and reset on reload. Prices are
                illustrative.
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
                      onClick={() => void refresh()}
                    >
                      Refresh
                    </Button>
                    {admin && isEditable(page) && (
                      <Button
                        appearance="primary"
                        disabled={loading}
                        onClick={() => setEditor({ collection: page })}
                      >
                        Create {collectionLabel(page)}
                      </Button>
                    )}
                  </div>
                )}
              </div>
              {!admin && (
                <div className="read-only-note">
                  <ShieldCheckmarkRegular /> Read-only workspace. Budget status, usage and
                  chargeback are scoped by the API to your user, team and department assignments.
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
              {page === 'dashboard' ? (
                <Dashboard api={api} fixtureMode={demo} />
              ) : page === 'overview' ? (
                <Overview
                  status={status}
                  usage={data.usage}
                  organizations={data.organizations}
                  assignments={data.assignments}
                  errors={errors}
                  loading={loading}
                  navigate={setPage}
                />
              ) : page === 'budgets' ? (
                <div className="surface data-panel">
                  {errors.budgetStatus ? (
                    <p className="empty-inline">Budget status unavailable. Refresh to retry.</p>
                  ) : (
                    <BudgetStatusTable
                      status={status}
                      organizations={admin ? data.organizations : []}
                      assignments={admin ? data.assignments : []}
                      loading={loading}
                    />
                  )}
                  {admin && (
                    <>
                      <div className="section-heading">
                        <h2>Configured monthly budgets</h2>
                      </div>
                      {errors.budgets ? (
                        <p className="empty-inline">Budgets unavailable. Refresh to retry.</p>
                      ) : (
                        <RecordBrowser
                          collection="budgets"
                          records={data.budgets}
                          organizations={data.organizations}
                          admin
                          loading={loading}
                          onEdit={(record) => setEditor({ collection: 'budgets', record })}
                          onDelete={(id) => {
                            setMutationError('');
                            setDeleting({ collection: 'budgets', id });
                          }}
                        />
                      )}
                    </>
                  )}
                </div>
              ) : page === 'usage' ? (
                errors.usage ? (
                  <p className="empty-inline">Usage is unavailable. Refresh to retry.</p>
                ) : (
                  <section className="surface data-panel">
                    <UsageTable records={data.usage} />
                  </section>
                )
              ) : page === 'chargeback' ? (
                <ChargebackReport api={api} refreshKey={loadedAt} />
              ) : page === 'models' ? (
                <ModelInventory
                  models={data.models}
                  prices={admin ? data.prices : []}
                  modelsError={errors.models}
                  pricesError={errors.prices}
                  loading={loading}
                  showPrices={admin}
                />
              ) : isEditable(page) ? (
                errors[page] ? (
                  <p className="empty-inline">{page} are unavailable. Refresh to retry.</p>
                ) : (
                  <RecordBrowser
                    key={page}
                    collection={page}
                    records={data[page] as EditableRecord[]}
                    organizations={data.organizations}
                    admin={admin}
                    loading={loading}
                    onEdit={(record) => setEditor({ collection: page, record })}
                    onDelete={(id) => {
                      setMutationError('');
                      setDeleting({ collection: page, id });
                    }}
                  />
                )
              ) : null}
              <footer className="page-footer">
                <span>
                  {loadedAt
                    ? `Last refresh attempt ${utcTime(loadedAt)}`
                    : 'Awaiting first refresh'}
                </span>
                <span>USD · UTC calendar months · OpenAI Chat Completions and Responses</span>
              </footer>
            </>
          )}
        </main>
      </div>
      {editor && admin && (
        <RecordEditor
          collection={editor.collection}
          record={editor.record}
          organizations={data.organizations}
          assignments={data.assignments}
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
                  <strong>{deleting.id}</strong> will be removed from {deleting.collection}.
                  Existing usage history is not deleted.
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
                  onClick={() => void confirmDelete()}
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
