export interface Person {
  id: string;
  display_name: string;
  default_split_weight: number;
}

export interface CellData {
  value: number;
  realized: number;
  projected: number;
  installments: number;
  source: "realized" | "hybrid" | "projected" | "installment" | "override";
  note: string | null;
  threshold?: number | null;
  utilization_pct?: number | null;
  alarm_severity?: "critical" | "warning" | null;
}

export interface SpreadsheetRow {
  row_id: string;
  section: "income" | "shared" | "annual" | "personal" | "uncategorized";
  kind: "income" | "expense";
  parent_category_id: string | null;
  parent_category_name: string;
  category_id: string;
  category_name: string;
  scope: "shared" | "personal";
  owner_person_id: string | null;
  owner_display_name: string;
  is_annual: boolean;
  is_discretionary?: boolean;
  monthly_budget_cap?: number | null;
  warning_threshold_pct?: number;
  cut_target_pct?: number;
  projection_method: string;
  cells: Record<string, CellData>;
  total_year_1: number;
  total_year_2: number;
  monthly_avg: number;
}

export interface ThresholdAlarm {
  row_id: string;
  month: string;
  severity: "critical" | "warning";
  category_id: string;
  category_name: string;
  parent_category_name: string;
  scope: "shared" | "personal";
  owner_person_id: string | null;
  owner_display_name: string;
  realized: number;
  projected: number;
  evaluated_amount: number;
  threshold: number;
  threshold_source: "yaml_threshold" | "historical_avg";
  warning_threshold_pct: number;
  utilization_pct: number;
  overage: number;
  top_merchants: Array<{ name: string; amount: number }>;
}

export interface CostCutOpportunity {
  category_id: string;
  category_name: string;
  parent_category_name: string;
  is_discretionary: boolean;
  over_threshold: boolean;
  configured_threshold: number | null;
  current_monthly_avg: number;
  total_ytd: number;
  cut_target_pct: number;
  suggested_monthly_cap: number;
  potential_monthly_savings: number;
  potential_annual_savings: number;
  top_merchants: Array<{
    name: string;
    total_ytd: number;
    monthly_avg: number;
    tx_count: number;
  }>;
}

export interface SubscriptionDrain {
  merchant: string;
  charges_count: number;
  monthly_avg: number;
  annualized_cost: number;
  total_ytd: number;
}

export interface AlertsAndCutsData {
  month: string;
  elapsed_months_analyzed: number;
  critical_alarms_count: number;
  warning_alarms_count: number;
  alarms: ThresholdAlarm[];
  total_potential_monthly_savings: number;
  total_potential_annual_savings: number;
  opportunities: CostCutOpportunity[];
  subscription_drains: SubscriptionDrain[];
}

export interface MonthSummary {
  income: number;
  expenses: number;
  shared_expenses: number;
  net_cashflow: number;
  projected_balance: number;
  savings_rate_pct: number;
}

export interface SettlementTransfer {
  from_person_id: string;
  from_display_name: string;
  to_person_id: string;
  to_display_name: string;
  amount: number;
}

export interface SettlementMember {
  person_id: string;
  display_name: string;
  default_weight: number;
  paid: number;
  target_share: number;
  net_balance: number;
}

export interface SettlementData {
  month: string;
  total_shared_expenses: number;
  transaction_count?: number;
  members: SettlementMember[];
  transfers: SettlementTransfer[];
}

export interface WealthPosition {
  id: string;
  person_id: string;
  person_name: string;
  account_type: "BANK" | "INVESTMENT";
  subtype: string;
  name: string;
  balance: number;
  is_emergency_fund: boolean;
}

export interface EmergencyFundSummary {
  target_months: number;
  avg_monthly_expenses: number;
  target_amount: number;
  selected_reserve_balance: number;
  excluded_balance: number;
  funded_pct: number;
  surplus_or_deficit_pct: number;
  surplus_or_deficit_amount: number;
  coverage_months: number;
  status: "surplus" | "on_track" | "shortfall";
  selected_positions_count: number;
  total_positions_count: number;
}

export interface WealthByPerson {
  person_id: string;
  display_name: string;
  cash_balance: number;
  investments_balance: number;
  total_saved: number;
  credit_card_balance: number;
  net_liquidity: number;
}

export interface WealthSummary {
  total_saved: number;
  cash_balance: number;
  investments_balance: number;
  credit_card_balance: number;
  net_liquidity: number;
  active_positions_count: number;
  positions: WealthPosition[];
  emergency_fund?: EmergencyFundSummary;
  by_person: WealthByPerson[];
}

export interface SpreadsheetMatrix {
  base_year: number;
  next_year: number;
  current_month: string;
  currency: string;
  annual_mode: "cash" | "monthly_provision";
  scope_filter: "all" | "shared" | "personal" | "annual";
  person_id: string | null;
  months: string[];
  people: Person[];
  starting_cash_balance: number;
  wealth_summary?: WealthSummary;
  alerts_and_cuts?: AlertsAndCutsData;
  uncategorized_count: number;
  rows: SpreadsheetRow[];
  summary: Record<string, MonthSummary>;
  current_month_settlement: SettlementData;
}

export interface SyncItemHealth {
  item_id: string;
  source_id: string;
  label: string;
  connector_name: string | null;
  status: string;
  execution_status: string | null;
  consent_expires_at: string | null;
  days_until_expiry: number | null;
  expiry_warning: boolean;
  last_updated_at: string | null;
}

export interface SyncHealth {
  items: SyncItemHealth[];
  accounts: Array<{
    id: string;
    person_id: string;
    name: string;
    account_type: string;
    current_balance: number;
  }>;
}

export interface CategoryTree {
  id: string;
  name: string;
  kind: "income" | "expense";
  default_scope: "shared" | "personal";
  subcategories: Array<{
    id: string;
    name: string;
    kind: "income" | "expense";
    default_scope: "shared" | "personal";
    is_annual: boolean;
  }>;
}

export interface ProjectionComponent {
  kind: string;
  label: string;
  detail: string;
  amount: number;
}

export interface CellBreakdown {
  month: string;
  category_id: string;
  scope: "shared" | "personal";
  owner_person_id: string | null;
  projection_explanation?: {
    method: string;
    month_state: "past" | "current" | "future";
    display_rule: string;
    components: ProjectionComponent[];
  };
  transactions: Array<{
    id: string;
    date: string;
    description: string;
    amount: number;
    paid_by_person_id: string;
    scope: string;
    installment: string | null;
    categorization_source: string;
  }>;
  projection_rules: Array<{
    id: string;
    name: string;
    rule_kind: string;
    frequency: string;
    amount: number;
  }>;
  override: {
    id: string;
    amount: number;
    note: string | null;
    updated_by: string;
  } | null;
}

export interface TransactionItem {
  id: string;
  date: string;
  competence_month: string;
  description: string;
  amount: number;
  currency: string;
  category_id: string | null;
  scope: "shared" | "personal";
  paid_by_person_id: string;
  owner_person_id: string | null;
  installment: string | null;
  categorization_source: string;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getSpreadsheet(params: {
    base_year?: number;
    annual_mode: "cash" | "monthly_provision";
    scope_filter: "all" | "shared" | "personal" | "annual";
    person_id?: string | null;
    emergency_months?: number;
  }) {
    const qs = new URLSearchParams({
      annual_mode: params.annual_mode,
      scope_filter: params.scope_filter,
    });
    if (params.base_year) qs.set("base_year", String(params.base_year));
    if (params.person_id) qs.set("person_id", params.person_id);
    if (params.emergency_months) qs.set("emergency_months", String(params.emergency_months));
    return fetchJson<SpreadsheetMatrix>(`/api/spreadsheet?${qs.toString()}`);
  },

  toggleEmergencyFundAccount(accountId: string, isEmergencyFund: boolean) {
    return fetchJson(`/api/accounts/${accountId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_emergency_fund: isEmergencyFund }),
    });
  },

  getSyncHealth() {
    return fetchJson<SyncHealth>("/api/sync/health");
  },

  getCategories() {
    return fetchJson<{ categories: CategoryTree[] }>("/api/categories");
  },

  getSettlement(month: string) {
    return fetchJson<SettlementData>(`/api/settlement/${month}`);
  },

  getAlertsAndCuts(month: string) {
    return fetchJson<AlertsAndCutsData>(`/api/alerts/budget?month=${encodeURIComponent(month)}`);
  },

  getCellBreakdown(params: {
    month: string;
    category_id: string;
    scope: "shared" | "personal";
    owner_person_id: string | null;
    annual_mode: "cash" | "monthly_provision";
  }) {
    const qs = new URLSearchParams({
      month: params.month,
      category_id: params.category_id,
      scope: params.scope,
      annual_mode: params.annual_mode,
    });
    if (params.owner_person_id) qs.set("owner_person_id", params.owner_person_id);
    return fetchJson<CellBreakdown>(`/api/spreadsheet/cell?${qs.toString()}`);
  },

  upsertOverride(body: {
    competence_month: string;
    category_id: string;
    scope: "shared" | "personal";
    owner_person_id: string | null;
    amount: number;
    note?: string;
  }) {
    return fetchJson("/api/spreadsheet/override", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  deleteOverride(params: {
    month: string;
    category_id: string;
    scope: "shared" | "personal";
    owner_person_id: string | null;
  }) {
    const qs = new URLSearchParams({
      month: params.month,
      category_id: params.category_id,
      scope: params.scope,
    });
    if (params.owner_person_id) qs.set("owner_person_id", params.owner_person_id);
    return fetchJson(`/api/spreadsheet/override?${qs.toString()}`, { method: "DELETE" });
  },

  listUncategorized() {
    return fetchJson<{ count: number; transactions: TransactionItem[] }>(
      "/api/transactions?uncategorized_only=true&limit=100"
    );
  },

  patchTransaction(
    txId: string,
    body: {
      category_id?: string;
      scope?: "shared" | "personal";
      owner_person_id?: string | null;
      is_internal_transfer?: boolean;
    }
  ) {
    return fetchJson(`/api/transactions/${txId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  triggerSync() {
    return fetchJson<{ results: Array<Record<string, unknown>> }>("/api/sync/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  },

  seedDemo() {
    return fetchJson<{ status: string; inserted: number }>("/api/demo/seed", {
      method: "POST",
    });
  },

  async uploadStatement(file: File, personId: string, accountName: string, defaultScope: string) {
    const form = new FormData();
    form.append("file", file);
    form.append("person_id", personId);
    form.append("account_name", accountName);
    form.append("default_scope", defaultScope);
    return fetchJson<{ parsed: number; inserted: number; skipped_duplicates: number }>(
      "/api/imports/upload",
      { method: "POST", body: form }
    );
  },
};

export function formatCurrency(value: number, currency = "BRL"): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatMonthShort(monthKey: string): string {
  const [y, m] = monthKey.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const idx = Math.max(0, Math.min(11, Number(m) - 1));
  return `${names[idx]} ${y.slice(2)}`;
}
