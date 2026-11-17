import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Avatar,
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  NavDrawer,
  NavDrawerBody,
  NavItem,
  NavSectionHeader,
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowClockwiseRegular,
  ArrowExitRegular,
  BrainCircuitRegular,
  BuildingRegular,
  ChartMultipleRegular,
  DataTrendingRegular,
  HomeRegular,
  PersonAccountsRegular,
  ReceiptMoneyRegular,
  SearchRegular,
  ShieldCheckmarkRegular,
  TagRegular,
  WalletRegular,
} from '@fluentui/react-icons';
import { BudgetStatusTable } from './components/BudgetStatusTable';
import { ChargebackReport } from './components/ChargebackReport';
import { ConfigurationTable } from './components/ConfigurationTable';
import { Dashboard } from './components/Dashboard';
import { InsightsPanel } from './components/InsightsPanel';
import { ModelInventory } from './components/ModelInventory';
import { Overview } from './components/Overview';
import { Unavailable } from './components/Unavailable';
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
import { budgetInsights } from './insights/budgetInsights';
import {
  assignmentInsights,
  modelInsights,
  organizationInsights,
  priceInsights,
} from './insights/catalogInsights';
import { sortInsights, type Insight, type InsightAction } from './insights/types';
import { usageInsights } from './insights/usageInsights';
import type { Page } from './pages';
import { RecordEditor } from './RecordEditor';
import { track } from './telemetry';

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
type NavSection = 'Monitor' | 'Manage' | 'Reference';
const pages: {
  id: Page;
  label: string;
  icon: React.ReactElement;
  section: NavSection;
  adminOnly?: boolean;
}[] = [
  { id: 'overview', label: 'Overview', icon: <HomeRegular />, section: 'Monitor' },
  { id: 'budgets', label: 'Monthly budgets', icon: <WalletRegular />, section: 'Monitor' },
  { id: 'usage', label: 'Usage records', icon: <DataTrendingRegular />, section: 'Monitor' },
  { id: 'chargeback', label: 'Chargeback', icon: <ReceiptMoneyRegular />, section: 'Monitor' },
  {
    id: 'dashboard',
    label: 'Azure dashboard',
    icon: <ChartMultipleRegular />,
    section: 'Monitor',
    adminOnly: true,
  },
  {
    id: 'organizations',
    label: 'Organization units',
    icon: <BuildingRegular />,
    section: 'Manage',
    adminOnly: true,
  },
  {
    id: 'assignments',
    label: 'User assignments',
    icon: <PersonAccountsRegular />,
    section: 'Manage',
    adminOnly: true,
  },
  {
    id: 'prices',
    label: 'OpenAI price cards',
    icon: <TagRegular />,
    section: 'Manage',
    adminOnly: true,
  },
  { id: 'models', label: 'Model inventory', icon: <BrainCircuitRegular />, section: 'Reference' },
];
const healthyMessages: Record<Page, string> = {
  overview: 'Every budget is below 80% of its limit.',
  budgets: 'Every budget is below 80% of its limit, enabled, and covered at each level.',
  organizations: 'Every team has an enabled department and assigned users.',
  assignments: 'Every user is assigned to an enabled team in the right department.',
  prices: 'Every price card is pinned by a model and has sensible rates.',
  models: 'Every model has exactly one price card for its pinned version.',
  usage: 'Every recent request reported usage.',
  chargeback: 'No unknown requests, estimates or unallocated rows.',
  dashboard: 'All tiles loaded.',
};
const navSections: NavSection[] = ['Monitor', 'Manage', 'Reference'];
const errorLabels: Record<keyof Errors, string> = {
  budgets: 'Budgets',
  organizations: 'Organization units',
  assignments: 'User assignments',
  prices: 'Price cards',
  models: 'Model inventory',
  usage: 'Usage records',
  budgetStatus: 'Budget status',
  chargeback: 'Chargeback',
};
const descriptions: Record<Page, string> = {
  overview: 'Monthly dollar budgets and actual spend for your departments, teams and users.',
  budgets: 'Monthly dollar limits for departments, teams and users, resetting each UTC month.',
  organizations: 'Departments and teams, with their business unit and cost center.',
  assignments: 'Assign each Entra user to a team; their department follows the team.',
  prices: 'Versioned input, cached-input and output rates per million tokens.',
  models: 'Model aliases, provider deployments and pinned price versions.',
  usage: 'Provider-reported actual usage, including streams with unknown usage.',
  chargeback: 'Monthly actual spend by department, team and user for cost allocation.',
  dashboard: 'Gateway traffic, token and accounting charts from the deployed Azure dashboard.',
};

/** Narrow navigation pages to configuration routes that support portal mutations. */
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

/** Search loaded authorized records locally; this does not request a broader API result set. */
function RecordBrowser({
  collection,
  records,
  organizations,
  admin,
  loading,
  onEdit,
  onDelete,
  budgetStatus,
}: {
  collection: EditableCollection;
  records: EditableRecord[];
  organizations: Organization[];
  admin: boolean;
  loading: boolean;
  onEdit: (record: EditableRecord) => void;
  onDelete: (id: string) => void;
  budgetStatus?: BudgetStatus[];
}) {
  const [search, setSearch] = useState('');
  const filtered = records.filter((record) =>
    JSON.stringify(record).toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <section className="surface">
      <div className="table-toolbar">
        <Input
          aria-label={`Search ${collection}`}
          placeholder={`Search ${collection}…`}
          contentBefore={<SearchRegular />}
          value={search}
          onChange={(_, data) => setSearch(data.value)}
        />
        <span className="secondary">
          {filtered.length} {filtered.length === 1 ? 'record' : 'records'}
        </span>
      </div>
      <ConfigurationTable
        collection={collection}
        records={filtered}
        organizations={organizations}
        admin={admin}
        onEdit={onEdit}
        onDelete={onDelete}
        budgetStatus={budgetStatus}
      />
      {!filtered.length && !loading && (
        <div className="empty-state">
          <SearchRegular />
          <h3>No matching records</h3>
          <p>Clear the search, refresh, or create a new {collectionLabel(collection)}.</p>
        </div>
      )}
    </section>
  );
}

/** Role-aware workspace shell; all data access and mutation authorization remain API-enforced. */
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

  /** Fetch independent collections concurrently while retaining per-collection failure states. */
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
    // One unavailable endpoint must not hide successfully loaded collections.
    const results = await Promise.allSettled(tasks.map((task) => task.run()));
    const failureCount = results.filter((result) => result.status === 'rejected').length;
    track(
      'portal_refresh',
      { outcome: failureCount ? 'partial_failure' : 'success' },
      { collectionCount: tasks.length, failureCount, durationMs: performance.now() - start },
    );
    // Superseded refreshes cannot overwrite newer data or state after effect cleanup.
    if (requestId !== sequence.current) return;
    // Failed collections are cleared rather than masquerading as fresh cached results.
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

  /** Reject obvious duplicate creates locally, then reload the API's canonical saved state. */
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

  /** Delete only after explicit confirmation; refresh history/configuration independently afterward. */
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

  const insights = useMemo<Insight[]>(() => {
    if (!loadedAt) return [];
    const budgetContext = {
      status,
      budgets: admin && !errors.budgets ? data.budgets : undefined,
      organizations: admin && !errors.organizations ? data.organizations : undefined,
      assignments: admin && !errors.assignments ? data.assignments : undefined,
      admin,
    };
    const budgets = errors.budgetStatus ? [] : budgetInsights(budgetContext);
    const usage = errors.usage ? [] : usageInsights(data.usage, admin);
    switch (page) {
      case 'overview':
        return sortInsights([...budgets, ...usage.filter((item) => item.id === 'unknown-usage')]);
      case 'budgets':
        return budgets;
      case 'usage':
        return usage;
      case 'models':
        return errors.models
          ? []
          : modelInsights(data.models, errors.prices ? [] : data.prices, admin && !errors.prices);
      case 'prices':
        return errors.prices ? [] : priceInsights(data.prices, data.models);
      case 'organizations':
        return errors.organizations || errors.assignments
          ? []
          : organizationInsights(data.organizations, data.assignments);
      case 'assignments':
        return errors.assignments || errors.organizations
          ? []
          : assignmentInsights(data.assignments, data.organizations);
      default:
        return [];
    }
  }, [loadedAt, page, status, data, errors, admin]);

  // An all-clear is only meaningful when there is data it was checked against.
  const hasSubject: Record<Page, boolean> = {
    overview: status.length > 0,
    budgets: status.length > 0 || data.budgets.length > 0,
    usage: data.usage.length > 0,
    models: data.models.length > 0,
    prices: data.prices.length > 0,
    organizations: data.organizations.length > 0,
    assignments: data.assignments.length > 0,
    chargeback: false,
    dashboard: false,
  };

  /** Perform a recommended action: edits and creates are administrator-only and API-enforced. */
  function runInsightAction(action: InsightAction) {
    setNotice('');
    if (action.kind === 'navigate') setPage(action.page);
    else if (!admin) return;
    else if (action.kind === 'create') setEditor({ collection: action.collection });
    else if (action.kind === 'edit') {
      const record = (data[action.collection] as EditableRecord[]).find(
        (item) => item.id === action.id,
      );
      if (record) setEditor({ collection: action.collection, record });
      else setPage(action.collection);
    }
  }

  const current = pages.find((item) => item.id === page);
  const roleLabel = admin ? 'Administrator' : canRead ? 'Reader' : 'Unassigned';
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
            AI Budget Control
            <span className="brand-sub">Per-dollar rate limits</span>
          </span>
        </a>
        <NavDrawer
          open
          type="inline"
          selectedValue={page}
          onNavItemSelect={(_, data) => {
            setPage(data.value as Page);
            setNotice('');
          }}
          aria-label="Primary navigation"
          className="nav-drawer"
        >
          <NavDrawerBody>
            {navSections.map((section) => {
              const items = pages.filter(
                (item) => item.section === section && (!item.adminOnly || admin),
              );
              if (!items.length) return null;
              return (
                <div key={section}>
                  <NavSectionHeader>{section}</NavSectionHeader>
                  {items.map((item) => (
                    <NavItem key={item.id} value={item.id} icon={item.icon} as="button">
                      {item.label}
                    </NavItem>
                  ))}
                </div>
              );
            })}
          </NavDrawerBody>
        </NavDrawer>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <Badge appearance="outline" color="informative">
            {cloud === 'government' ? 'Azure Government' : 'Azure Commercial'}
          </Badge>
          <div className="account">
            <Badge appearance="tint" color={admin ? 'brand' : canRead ? 'informative' : 'subtle'}>
              {roleLabel}
            </Badge>
            {profileGreeting ?? (
              <div className="profile-greeting">
                <Avatar name={identity} size={28} color="colorful" aria-hidden="true" />
                <span className="identity">Howdy {identity}!</span>
              </div>
            )}
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
                <strong>Local demo — fixture data only.</strong> No authentication or Azure calls.
                Edits live only in this browser session and reset on reload; prices are
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
                  <h1>{current?.label}</h1>
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
                <MessageBar intent="info">
                  <MessageBarBody>
                    Read-only. Budgets, usage and chargeback are limited to your user, team and
                    department.
                  </MessageBarBody>
                </MessageBar>
              )}
              {Object.entries(errors).map(([collection, message]) => (
                <MessageBar key={collection} intent="error">
                  <MessageBarBody>
                    <strong>{errorLabels[collection as keyof Errors]}:</strong> {message} Use
                    Refresh to retry. No sample data has been substituted.
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
                  <Spinner size="tiny" label="Loading…" />
                </div>
              )}
              {loadedAt &&
                page !== 'dashboard' &&
                page !== 'chargeback' &&
                (insights.length > 0 || hasSubject[page]) && (
                  <InsightsPanel
                    insights={insights}
                    healthy={healthyMessages[page]}
                    onAction={runInsightAction}
                  />
                )}
              {page === 'dashboard' ? (
                <Dashboard api={api} fixtureMode={demo} onAction={runInsightAction} />
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
                <div className="surface">
                  {admin ? (
                    <>
                      {errors.budgets ? (
                        <Unavailable what="Budgets" />
                      ) : (
                        <RecordBrowser
                          collection="budgets"
                          records={data.budgets}
                          organizations={data.organizations}
                          admin
                          loading={loading}
                          budgetStatus={status}
                          onEdit={(record) => setEditor({ collection: 'budgets', record })}
                          onDelete={(id) => {
                            setMutationError('');
                            setDeleting({ collection: 'budgets', id });
                          }}
                        />
                      )}
                    </>
                  ) : errors.budgetStatus ? (
                    <Unavailable what="Budget status" />
                  ) : (
                    <BudgetStatusTable status={status} loading={loading} />
                  )}
                </div>
              ) : page === 'usage' ? (
                errors.usage ? (
                  <Unavailable what="Usage" />
                ) : (
                  <section className="surface">
                    <UsageTable records={data.usage} />
                  </section>
                )
              ) : page === 'chargeback' ? (
                <ChargebackReport
                  api={api}
                  refreshKey={loadedAt}
                  admin={admin}
                  onAction={runInsightAction}
                />
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
                  <Unavailable what={errorLabels[page]} />
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
                {loadedAt ? `Last refreshed ${utcTime(loadedAt)}` : 'Awaiting first refresh'}
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
                  <MessageBar intent="error" role="alert">
                    <MessageBarBody>{mutationError}</MessageBarBody>
                  </MessageBar>
                )}
              </DialogContent>
              <DialogActions>
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
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      )}
    </div>
  );
}
