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
  projection_method: string;
  cells: Record<string, CellData>;
  total_year_1: number;
  total_year_2: number;
  monthly_avg: number;
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

export interface CellBreakdown {
  month: string;
  category_id: string;
  scope: "shared" | "personal";
  owner_person_id: string | null;
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
  }) {
    const qs = new URLSearchParams({
      annual_mode: params.annual_mode,
      scope_filter: params.scope_filter,
    });
    if (params.base_year) qs.set("base_year", String(params.base_year));
    if (params.person_id) qs.set("person_id", params.person_id);
    return fetchJson<SpreadsheetMatrix>(`/api/spreadsheet?${qs.toString()}`);
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
