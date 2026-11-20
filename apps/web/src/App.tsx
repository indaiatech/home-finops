import {
  AlertTriangle,
  ArrowRight,
  Calendar,
  ChevronDown,
  ChevronUp,
  CreditCard,
  Database,
  Download,
  Landmark,
  PiggyBank,
  RefreshCw,
  Scale,
  Sparkles,
  Upload,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type AlertsAndCutsData,
  type CategoryTree,
  type SettlementData,
  type SpreadsheetMatrix,
  type SpreadsheetRow,
  type SyncHealth,
  formatCurrency,
  formatMonthShort,
} from "./api";
import { AlertsAndCutsPanel } from "./components/AlertsAndCutsPanel";
import { CellDrawer } from "./components/CellDrawer";
import { ImportModal } from "./components/ImportModal";
import { SpreadsheetGrid } from "./components/SpreadsheetGrid";
import { TriageModal } from "./components/TriageModal";

export default function App() {
  const [matrix, setMatrix] = useState<SpreadsheetMatrix | null>(null);
  const [syncHealth, setSyncHealth] = useState<SyncHealth | null>(null);
  const [categories, setCategories] = useState<CategoryTree[]>([]);
  const [settlement, setSettlement] = useState<SettlementData | null>(null);
  const [settlementMonth, setSettlementMonth] = useState<string>("");
  const [alertsAndCuts, setAlertsAndCuts] = useState<AlertsAndCutsData | null>(null);
  const [alertsMonth, setAlertsMonth] = useState<string>("");

  const [scopeFilter, setScopeFilter] = useState<"all" | "shared" | "personal" | "annual">("all");
  const [personFilter, setPersonFilter] = useState<string>("");
  const [annualMode, setAnnualMode] = useState<"cash" | "monthly_provision">("cash");
  const [zoomMode, setZoomMode] = useState<"24m" | "current_year" | "next_12m">("24m");
  const [emergencyMonths, setEmergencyMonths] = useState<number>(6);

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const [selectedCell, setSelectedCell] = useState<{
    row: SpreadsheetRow;
    month: string;
  } | null>(null);
  const [showTriage, setShowTriage] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showPositions, setShowPositions] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sheet, health, cats] = await Promise.all([
        api.getSpreadsheet({
          annual_mode: annualMode,
          scope_filter: scopeFilter,
          person_id: personFilter || null,
          emergency_months: emergencyMonths,
        }),
        api.getSyncHealth(),
        api.getCategories(),
      ]);
      setMatrix(sheet);
      setSyncHealth(health);
      setCategories(cats.categories);
      if (!settlementMonth) {
        setSettlementMonth(sheet.current_month);
        setSettlement(sheet.current_month_settlement);
      } else {
        const s = await api.getSettlement(settlementMonth);
        setSettlement(s);
      }
      if (!alertsMonth) {
        setAlertsMonth(sheet.current_month);
        setAlertsAndCuts(sheet.alerts_and_cuts || null);
      } else {
        const ac = await api.getAlertsAndCuts(alertsMonth);
        setAlertsAndCuts(ac);
      }
    } catch (err) {
      setToast(`Failed to load FinOps API: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [annualMode, scopeFilter, personFilter, settlementMonth, alertsMonth, emergencyMonths]);

  async function handleToggleEmergencyAccount(accountId: string, currentVal: boolean) {
    await api.toggleEmergencyFundAccount(accountId, !currentVal);
    await loadAll();
  }

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleSettlementMonthChange(month: string) {
    setSettlementMonth(month);
    const data = await api.getSettlement(month);
    setSettlement(data);
  }

  async function handleAlertsMonthChange(month: string) {
    setAlertsMonth(month);
    const data = await api.getAlertsAndCuts(month);
    setAlertsAndCuts(data);
  }

  async function handleSyncPluggy() {
    setSyncing(true);
    setToast(null);
    try {
      const res = await api.triggerSync();
      const summary = res.results
        .map((r) => `${String(r.source_id)}: ${String(r.status)}`)
        .join(" • ");
      setToast(`Sync complete (${summary})`);
      await loadAll();
    } catch (err) {
      setToast(`Sync error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSyncing(false);
    }
  }

  async function handleSeedDemo() {
    setSyncing(true);
    setToast(null);
    try {
      const res = await api.seedDemo();
      setToast(`Loaded synthetic demo dataset (${res.inserted} transactions).`);
      await loadAll();
    } finally {
      setSyncing(false);
    }
  }

  const visibleMonths = useMemo(() => {
    if (!matrix) return [];
    if (zoomMode === "current_year") {
      return matrix.months.slice(0, 12);
    }
    if (zoomMode === "next_12m") {
      const idx = matrix.months.indexOf(matrix.current_month);
      if (idx >= 0) return matrix.months.slice(idx, idx + 12);
    }
    return matrix.months;
  }, [matrix, zoomMode]);

  const activeSettlement = settlement || matrix?.current_month_settlement || null;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-800/90 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center justify-between gap-3 px-4 py-3.5 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/40">
              <Database className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold tracking-tight text-white">FinOps</h1>
                {matrix && (
                  <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[11px] font-medium text-slate-300">
                    {matrix.base_year} – {matrix.next_year}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                24-Month Household Spreadsheet • Multi-Account Meu Pluggy • Hermes MCP
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {matrix && matrix.uncategorized_count > 0 && (
              <button
                onClick={() => setShowTriage(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/25"
              >
                <AlertTriangle className="h-3.5 w-3.5" />
                {matrix.uncategorized_count} Uncategorized
              </button>
            )}

            <button
              onClick={handleSyncPluggy}
              disabled={syncing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
              Sync Pluggy
            </button>

            <button
              onClick={() => setShowImport(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
            >
              <Upload className="h-3.5 w-3.5" />
              CSV / OFX
            </button>

            <a
              href={`/api/spreadsheet/export?fmt=xlsx&annual_mode=${annualMode}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-800"
            >
              <Download className="h-3.5 w-3.5" />
              XLSX
            </a>

            <button
              onClick={handleSeedDemo}
              disabled={syncing}
              title="Populate synthetic 2-person demo data"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900/60 px-2.5 py-1.5 text-xs text-slate-400 hover:border-slate-700 hover:text-slate-200"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Demo Seed
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1680px] space-y-4 px-4 py-4 sm:px-6">
        {toast && (
          <div className="flex items-center justify-between rounded-xl border border-emerald-700/50 bg-emerald-950/40 px-4 py-2.5 text-xs text-emerald-200">
            <span>{toast}</span>
            <button onClick={() => setToast(null)} className="text-emerald-400 hover:underline">
              Dismiss
            </button>
          </div>
        )}

        {/* Household Savings & Liquidity Banner (Checking + Caixinhas/CDBs vs Credit Cards) */}
        {matrix?.wealth_summary && (
          <section className="rounded-xl border border-emerald-900/60 bg-gradient-to-r from-slate-900 via-slate-900/95 to-emerald-950/30 p-4 shadow-lg">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex flex-wrap items-center gap-6">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/40">
                    <PiggyBank className="h-6 w-6 text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                      Total Saved (Cash + Investments / CDB)
                    </div>
                    <div className="num text-2xl font-bold tracking-tight text-white">
                      {formatCurrency(matrix.wealth_summary.total_saved, matrix.currency)}
                    </div>
                  </div>
                </div>

                <div className="h-9 w-px bg-slate-800 hidden sm:block" />

                <div className="flex flex-wrap items-center gap-5">
                  <div>
                    <div className="flex items-center gap-1 text-[11px] text-slate-400">
                      <Landmark className="h-3.5 w-3.5 text-sky-400" />
                      Investments (RDB / CDB)
                    </div>
                    <div className="num mt-0.5 text-sm font-semibold text-sky-300">
                      {formatCurrency(matrix.wealth_summary.investments_balance, matrix.currency)}
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center gap-1 text-[11px] text-slate-400">
                      <Wallet className="h-3.5 w-3.5 text-emerald-400" />
                      Checking / Reserved
                    </div>
                    <div className="num mt-0.5 text-sm font-semibold text-slate-200">
                      {formatCurrency(matrix.wealth_summary.cash_balance, matrix.currency)}
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center gap-1 text-[11px] text-slate-400">
                      <CreditCard className="h-3.5 w-3.5 text-rose-400" />
                      Credit Cards Open
                    </div>
                    <div className="num mt-0.5 text-sm font-semibold text-rose-300">
                      -{formatCurrency(matrix.wealth_summary.credit_card_balance, matrix.currency)}
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] text-slate-400">Net Liquidity (After Cards)</div>
                    <div className="num mt-0.5 text-sm font-bold text-emerald-300">
                      {formatCurrency(matrix.wealth_summary.net_liquidity, matrix.currency)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {matrix.wealth_summary.by_person.map((pw) => (
                  <div
                    key={pw.person_id}
                    className="rounded-lg border border-slate-800 bg-slate-950/75 px-3 py-1.5 text-xs"
                  >
                    <span className="text-slate-400">{pw.display_name}: </span>
                    <span className="num font-semibold text-emerald-300">
                      {formatCurrency(pw.total_saved, matrix.currency)}
                    </span>
                  </div>
                ))}

                {matrix.wealth_summary.positions.length > 0 && (
                  <button
                    onClick={() => setShowPositions((v) => !v)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
                  >
                    {matrix.wealth_summary.emergency_fund
                      ? `${matrix.wealth_summary.emergency_fund.selected_positions_count}/${matrix.wealth_summary.active_positions_count} in Reserve`
                      : `${matrix.wealth_summary.active_positions_count} Positions`}
                    {showPositions ? (
                      <ChevronUp className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5" />
                    )}
                  </button>
                )}
              </div>
            </div>

            {/* Emergency Fund Reserve Section (Default 6 Months, Configurable Period & Account Selection) */}
            {matrix.wealth_summary.emergency_fund && (() => {
              const ef = matrix.wealth_summary.emergency_fund;
              const isSurplus = ef.surplus_or_deficit_amount >= 0;
              const barPct = Math.min(100, Math.max(0, Math.round(ef.funded_pct)));
              return (
                <div className="mt-3.5 rounded-xl border border-slate-800/90 bg-slate-950/75 p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                        Emergency Fund Reserve
                      </span>
                      <div className="inline-flex items-center rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-[11px]">
                        {[3, 6, 9, 12, 18, 24].map((m) => (
                          <button
                            key={m}
                            onClick={() => setEmergencyMonths(m)}
                            className={`rounded-md px-2 py-0.5 font-medium transition ${
                              emergencyMonths === m
                                ? "bg-emerald-600 text-white"
                                : "text-slate-400 hover:text-slate-200"
                            }`}
                          >
                            {m}m
                          </button>
                        ))}
                      </div>
                      <span className="num text-xs text-slate-400">
                        Coverage:{" "}
                        <strong className="text-white">
                          {ef.coverage_months.toFixed(1)} months
                        </strong>{" "}
                        (avg burn {formatCurrency(ef.avg_monthly_expenses, matrix.currency)}/mo)
                      </span>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`num rounded-lg border px-2.5 py-1 text-xs font-bold ${
                          isSurplus
                            ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                            : ef.funded_pct >= 80
                              ? "border-amber-500/40 bg-amber-500/15 text-amber-300"
                              : "border-rose-500/40 bg-rose-500/15 text-rose-300"
                        }`}
                      >
                        {isSurplus
                          ? `+${ef.surplus_or_deficit_pct.toFixed(1)}% Surplus (+${formatCurrency(ef.surplus_or_deficit_amount, matrix.currency)})`
                          : `${ef.surplus_or_deficit_pct.toFixed(1)}% Short (${formatCurrency(ef.surplus_or_deficit_amount, matrix.currency)})`}
                      </span>
                      <span className="num text-xs font-semibold text-slate-300">
                        {ef.funded_pct.toFixed(1)}% of {ef.target_months}m target
                      </span>
                    </div>
                  </div>

                  {/* Emergency Reserve Progress Bar */}
                  <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full transition-all ${
                        isSurplus
                          ? "bg-emerald-500"
                          : ef.funded_pct >= 80
                            ? "bg-amber-400"
                            : "bg-rose-500"
                      }`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>

                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
                    <div className="num">
                      Selected Reserve:{" "}
                      <strong className="text-emerald-300">
                        {formatCurrency(ef.selected_reserve_balance, matrix.currency)}
                      </strong>{" "}
                      / Target ({ef.target_months} mo):{" "}
                      <strong className="text-white">
                        {formatCurrency(ef.target_amount, matrix.currency)}
                      </strong>
                      {ef.excluded_balance > 0 && (
                        <span className="ml-2 text-slate-500">
                          ({formatCurrency(ef.excluded_balance, matrix.currency)} excluded)
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => setShowPositions((v) => !v)}
                      className="text-emerald-400 hover:underline"
                    >
                      {showPositions
                        ? "Hide account selector"
                        : "Choose which accounts/investments count toward Emergency Reserve"}
                    </button>
                  </div>
                </div>
              );
            })()}

            {showPositions && matrix.wealth_summary.positions.length > 0 && (
              <div className="mt-3 grid grid-cols-1 gap-2 border-t border-slate-800/80 pt-3 sm:grid-cols-2 lg:grid-cols-3">
                {matrix.wealth_summary.positions.map((pos) => (
                  <label
                    key={pos.id}
                    className={`flex cursor-pointer items-center justify-between rounded-lg border px-3 py-2 text-xs transition ${
                      pos.is_emergency_fund
                        ? "border-emerald-800/70 bg-slate-950/80"
                        : "border-slate-800/60 bg-slate-950/35 opacity-60"
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-2.5 pr-2">
                      <input
                        type="checkbox"
                        checked={pos.is_emergency_fund}
                        onChange={() =>
                          handleToggleEmergencyAccount(pos.id, pos.is_emergency_fund)
                        }
                        className="h-3.5 w-3.5 rounded border-slate-700 accent-emerald-500"
                      />
                      <div className="min-w-0">
                        <div className="truncate font-medium text-slate-200">{pos.name}</div>
                        <div className="text-[11px] text-slate-400">
                          {pos.person_name} • {pos.subtype} •{" "}
                          {pos.is_emergency_fund ? "In Emergency Reserve" : "Excluded"}
                        </div>
                      </div>
                    </div>
                    <div className="num shrink-0 font-semibold text-emerald-300">
                      {formatCurrency(pos.balance, matrix.currency)}
                    </div>
                  </label>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Top Summary Strip: Pluggy Health + Automatic Shared-Expense Settlement */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          {/* Settlement Engine Card */}
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 lg:col-span-7">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Scale className="h-4 w-4 text-sky-400" />
                <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                  Automatic Shared-Expense Settlement (General)
                </h2>
              </div>
              {matrix && (
                <select
                  value={settlementMonth || matrix.current_month}
                  onChange={(e) => handleSettlementMonthChange(e.target.value)}
                  className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-200"
                >
                  {matrix.months.slice(0, 12).map((m) => (
                    <option key={m} value={m}>
                      {formatMonthShort(m)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {activeSettlement && activeSettlement.members.length > 0 ? (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
                <div className="flex flex-wrap gap-3">
                  {activeSettlement.members.map((m) => (
                    <div
                      key={m.person_id}
                      className="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2"
                    >
                      <div className="text-[11px] text-slate-400">
                        {m.display_name} ({Math.round(m.default_weight * 100)}%)
                      </div>
                      <div className="num mt-0.5 text-xs text-slate-200">
                        Paid:{" "}
                        <span className="font-semibold">
                          {formatCurrency(m.paid, matrix?.currency)}
                        </span>{" "}
                        • Share: {formatCurrency(m.target_share, matrix?.currency)}
                      </div>
                    </div>
                  ))}
                </div>

                {activeSettlement.transfers.length > 0 ? (
                  <div className="flex items-center gap-2 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3.5 py-2 text-xs font-semibold text-sky-200">
                    <span>{activeSettlement.transfers[0].from_display_name}</span>
                    <ArrowRight className="h-3.5 w-3.5 text-sky-400" />
                    <span>{activeSettlement.transfers[0].to_display_name}:</span>
                    <span className="num text-sm text-white">
                      {formatCurrency(activeSettlement.transfers[0].amount, matrix?.currency)}
                    </span>
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">
                    No settlement transfer needed for this month.
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-2 text-xs text-slate-500">
                No shared expenses recorded in this month yet.
              </div>
            )}
          </section>

          {/* Pluggy Health Strip */}
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 lg:col-span-5">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                Meu Pluggy Connections
              </h2>
              <span className="text-[11px] text-slate-400">
                {syncHealth?.accounts.length ?? 0} linked accounts
              </span>
            </div>

            <div className="mt-3 space-y-2">
              {syncHealth && syncHealth.items.length > 0 ? (
                syncHealth.items.map((item) => (
                  <div
                    key={item.item_id}
                    className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs"
                  >
                    <div className="min-w-0 pr-2">
                      <div className="truncate font-medium text-slate-200">{item.label}</div>
                      <div className="text-[11px] text-slate-400">
                        {item.connector_name || "Pending first sync"}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {item.days_until_expiry !== null && (
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                            item.expiry_warning
                              ? "bg-amber-500/20 text-amber-300"
                              : "bg-slate-800 text-slate-300"
                          }`}
                        >
                          {item.days_until_expiry}d TTL
                        </span>
                      )}
                      <span
                        className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                          item.status === "UPDATED"
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {item.status}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-xs text-slate-500">
                  Configure Pluggy items in local/sources.yaml and click Sync Pluggy.
                </div>
              )}
            </div>
          </section>
        </div>

        {/* Threshold Alarms & Where We Can Cut Costs Section */}
        {matrix && (alertsAndCuts || matrix.alerts_and_cuts) && (
          <AlertsAndCutsPanel
            data={(alertsAndCuts || matrix.alerts_and_cuts)!}
            months={matrix.months}
            selectedMonth={alertsMonth || matrix.current_month}
            currency={matrix.currency}
            rows={matrix.rows}
            onChangeMonth={handleAlertsMonthChange}
            onSelectAlarmCell={(row, month) => setSelectedCell({ row, month })}
          />
        )}

        {/* Spreadsheet Filters & Mode Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-2.5">
          {/* Scope Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            {(
              [
                ["all", "Consolidated (All)"],
                ["shared", "General (Shared)"],
                ["personal", "Personal"],
                ["annual", "Annual Only"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setScopeFilter(key)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  scopeFilter === key
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-950 text-slate-300 hover:bg-slate-800"
                }`}
              >
                {label}
              </button>
            ))}

            {matrix && (
              <select
                value={personFilter}
                onChange={(e) => setPersonFilter(e.target.value)}
                className="ml-1 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-200"
              >
                <option value="">All Members</option>
                {matrix.people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Annual Mode + Horizon Zoom */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center rounded-lg border border-slate-800 bg-slate-950 p-0.5 text-xs">
              <button
                onClick={() => setAnnualMode("cash")}
                className={`rounded-md px-2.5 py-1 font-medium ${
                  annualMode === "cash"
                    ? "bg-violet-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Annual: Cash
              </button>
              <button
                onClick={() => setAnnualMode("monthly_provision")}
                className={`rounded-md px-2.5 py-1 font-medium ${
                  annualMode === "monthly_provision"
                    ? "bg-violet-600 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                Annual: 1/12 Provision
              </button>
            </div>

            <div className="inline-flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-950 p-0.5 text-xs">
              <Calendar className="ml-1.5 h-3.5 w-3.5 text-slate-400" />
              {(
                [
                  ["24m", "24m"],
                  ["current_year", `${matrix?.base_year || "Year 1"}`],
                  ["next_12m", "Next 12m"],
                ] as const
              ).map(([k, lbl]) => (
                <button
                  key={k}
                  onClick={() => setZoomMode(k)}
                  className={`rounded-md px-2 py-1 font-medium ${
                    zoomMode === k
                      ? "bg-slate-800 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {lbl}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Main 24-Month Spreadsheet */}
        {loading && !matrix ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-12 text-center text-sm text-slate-400">
            Loading 24-month financial spreadsheet...
          </div>
        ) : matrix ? (
          <>
            <SpreadsheetGrid
              matrix={matrix}
              visibleMonths={visibleMonths}
              onSelectCell={(row, month) => setSelectedCell({ row, month })}
              onOverrideSaved={loadAll}
            />
            <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
              <div className="flex flex-wrap items-center gap-4">
                <span>
                  <span className="font-medium text-slate-200">Solid</span> = Realized
                </span>
                <span>
                  <span className="italic text-sky-300">Italic</span> = Auto-Projected
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-amber-400" /> Manual Override
                </span>
                <span>
                  <span className="rounded bg-indigo-500/20 px-1 text-[10px] text-indigo-300">
                    inst
                  </span>{" "}
                  Credit-card installment
                </span>
              </div>
              <span>Click any cell for breakdown • Double-click current/future cells to edit</span>
            </div>
          </>
        ) : null}
      </main>

      {/* Cell Drill-Down Drawer */}
      {selectedCell && matrix && (
        <CellDrawer
          row={selectedCell.row}
          month={selectedCell.month}
          currency={matrix.currency}
          annualMode={annualMode}
          currentMonth={matrix.current_month}
          onClose={() => setSelectedCell(null)}
          onUpdated={loadAll}
        />
      )}

      {/* Uncategorized Triage Modal */}
      {showTriage && matrix && (
        <TriageModal
          people={matrix.people}
          categories={categories}
          currency={matrix.currency}
          onClose={() => setShowTriage(false)}
          onUpdated={loadAll}
        />
      )}

      {/* CSV/OFX Import Modal */}
      {showImport && matrix && (
        <ImportModal
          people={matrix.people}
          onClose={() => setShowImport(false)}
          onImported={loadAll}
        />
      )}
    </div>
  );
}
