import {
  AlertOctagon,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Flame,
  Scissors,
  TrendingDown,
} from "lucide-react";
import { useState } from "react";
import {
  type AlertsAndCutsData,
  type SpreadsheetRow,
  formatCurrency,
  formatMonthShort,
} from "../api";

interface AlertsAndCutsPanelProps {
  data: AlertsAndCutsData;
  months: string[];
  selectedMonth: string;
  currency: string;
  rows: SpreadsheetRow[];
  onChangeMonth: (month: string) => void;
  onSelectAlarmCell: (row: SpreadsheetRow, month: string) => void;
}

export function AlertsAndCutsPanel({
  data,
  months,
  selectedMonth,
  currency,
  rows,
  onChangeMonth,
  onSelectAlarmCell,
}: AlertsAndCutsPanelProps) {
  const [showSubscriptions, setShowSubscriptions] = useState(false);

  function handleAlarmClick(rowId: string, month: string) {
    const found = rows.find((r) => r.row_id === rowId);
    if (found) {
      onSelectAlarmCell(found, month);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      {/* Left: Threshold Alarms Section */}
      <section className="rounded-xl border border-rose-900/50 bg-slate-900/70 p-4 shadow-lg lg:col-span-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-500/15 ring-1 ring-rose-500/40">
              <Flame className="h-4 w-4 text-rose-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-white">
                  Threshold Alarms
                </h2>
                {data.critical_alarms_count > 0 && (
                  <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-300 ring-1 ring-rose-500/40">
                    {data.critical_alarms_count} Critical
                  </span>
                )}
                {data.warning_alarms_count > 0 && (
                  <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300 ring-1 ring-amber-500/40">
                    {data.warning_alarms_count} Warning
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400">
                Categories exceeding or approaching YAML thresholds / historical baselines
              </p>
            </div>
          </div>

          <select
            value={selectedMonth}
            onChange={(e) => onChangeMonth(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-200"
          >
            {months.slice(0, 12).map((m) => (
              <option key={m} value={m}>
                {formatMonthShort(m)}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-3 max-h-[310px] space-y-2.5 overflow-y-auto pr-1">
          {data.alarms.length === 0 ? (
            <div className="rounded-lg border border-dashed border-emerald-800/50 bg-emerald-950/20 p-5 text-center text-xs text-emerald-300">
              No threshold alarms triggered for {formatMonthShort(selectedMonth)}.
            </div>
          ) : (
            data.alarms.map((alarm) => {
              const isCrit = alarm.severity === "critical";
              const barPct = Math.min(100, Math.round(alarm.utilization_pct));
              return (
                <div
                  key={`${alarm.row_id}-${alarm.month}`}
                  onClick={() => handleAlarmClick(alarm.row_id, alarm.month)}
                  className={`cursor-pointer rounded-xl border p-3 transition hover:brightness-110 ${
                    isCrit
                      ? "border-rose-500/40 bg-rose-950/25"
                      : "border-amber-500/40 bg-amber-950/20"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {isCrit ? (
                        <AlertOctagon className="h-4 w-4 shrink-0 text-rose-400" />
                      ) : (
                        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
                      )}
                      <div>
                        <div className="text-xs font-semibold text-white">
                          {alarm.parent_category_name} / {alarm.category_name}
                        </div>
                        <div className="text-[11px] text-slate-400">
                          {alarm.scope === "shared" ? "General (Shared)" : alarm.owner_display_name}{" "}
                          •{" "}
                          {alarm.threshold_source === "yaml_threshold"
                            ? "YAML Threshold"
                            : "Historical Avg Baseline"}
                        </div>
                      </div>
                    </div>

                    <div className="text-right">
                      <span
                        className={`num rounded px-1.5 py-0.5 text-[11px] font-bold ${
                          isCrit
                            ? "bg-rose-500/25 text-rose-200"
                            : "bg-amber-500/25 text-amber-200"
                        }`}
                      >
                        {alarm.utilization_pct.toFixed(0)}%
                      </span>
                      {alarm.overage > 0 && (
                        <div className="num mt-0.5 text-[11px] font-semibold text-rose-300">
                          +{formatCurrency(alarm.overage, currency)} over
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Utilization Progress Bar */}
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full ${
                        isCrit ? "bg-rose-500" : "bg-amber-400"
                      }`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>

                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                    <div className="num text-slate-300">
                      Current:{" "}
                      <span className="font-semibold text-white">
                        {formatCurrency(alarm.evaluated_amount, currency)}
                      </span>{" "}
                      / Limit:{" "}
                      <span className="font-medium text-slate-200">
                        {formatCurrency(alarm.threshold, currency)}
                      </span>
                    </div>

                    {alarm.top_merchants.length > 0 && (
                      <div className="truncate text-slate-400">
                        Top:{" "}
                        {alarm.top_merchants
                          .map((m) => `${m.name} (${formatCurrency(m.amount, currency)})`)
                          .join(", ")}
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      {/* Right: Where We Can Cut Costs Section */}
      <section className="rounded-xl border border-amber-900/50 bg-slate-900/70 p-4 shadow-lg lg:col-span-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/15 ring-1 ring-amber-500/40">
              <Scissors className="h-4 w-4 text-amber-400" />
            </div>
            <div>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-white">
                Where We Can Cut Costs
              </h2>
              <p className="text-[11px] text-slate-400">
                Ranked savings opportunities across discretionary & over-threshold categories
              </p>
            </div>
          </div>

          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-right">
            <div className="text-[10px] font-medium uppercase tracking-wider text-emerald-300">
              Potential Savings
            </div>
            <div className="num text-xs font-bold text-white">
              {formatCurrency(data.total_potential_monthly_savings, currency)}/mo{" "}
              <span className="text-emerald-300">
                ({formatCurrency(data.total_potential_annual_savings, currency)}/yr)
              </span>
            </div>
          </div>
        </div>

        <div className="mt-3 max-h-[310px] space-y-2.5 overflow-y-auto pr-1">
          {data.opportunities.map((opp) => (
            <div
              key={opp.category_id}
              className="rounded-xl border border-slate-800 bg-slate-950/75 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-white">
                      {opp.parent_category_name} / {opp.category_name}
                    </span>
                    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                      -{opp.cut_target_pct.toFixed(0)}% target
                    </span>
                    {opp.over_threshold && (
                      <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">
                        Above Limit
                      </span>
                    )}
                  </div>
                  <div className="num mt-0.5 text-[11px] text-slate-400">
                    Current Avg:{" "}
                    <span className="font-semibold text-slate-200">
                      {formatCurrency(opp.current_monthly_avg, currency)}/mo
                    </span>{" "}
                    → Suggested Cap:{" "}
                    <span className="font-semibold text-sky-300">
                      {formatCurrency(opp.suggested_monthly_cap, currency)}/mo
                    </span>
                  </div>
                </div>

                <div className="text-right">
                  <div className="num inline-flex items-center gap-1 text-xs font-bold text-emerald-400">
                    <TrendingDown className="h-3.5 w-3.5" />
                    Save {formatCurrency(opp.potential_monthly_savings, currency)}/mo
                  </div>
                  <div className="num text-[11px] font-medium text-emerald-300/80">
                    {formatCurrency(opp.potential_annual_savings, currency)} / year
                  </div>
                </div>
              </div>

              {opp.top_merchants.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {opp.top_merchants.map((m) => (
                    <span
                      key={m.name}
                      className="num rounded-md border border-slate-800 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300"
                    >
                      {m.name}:{" "}
                      <strong className="text-white">
                        {formatCurrency(m.monthly_avg, currency)}/mo
                      </strong>{" "}
                      ({m.tx_count}x)
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {/* Recurring Subscriptions Audit Toggle */}
          {data.subscription_drains.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
              <button
                onClick={() => setShowSubscriptions((v) => !v)}
                className="flex w-full items-center justify-between text-xs font-semibold text-slate-200"
              >
                <span>
                  Recurring Digital Subscriptions Audit ({data.subscription_drains.length} services)
                </span>
                {showSubscriptions ? (
                  <ChevronUp className="h-4 w-4 text-slate-400" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-slate-400" />
                )}
              </button>
              {showSubscriptions && (
                <div className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
                  {data.subscription_drains.map((sub) => (
                    <div
                      key={sub.merchant}
                      className="flex items-center justify-between text-[11px]"
                    >
                      <span className="text-slate-300">
                        {sub.merchant}{" "}
                        <span className="text-slate-500">({sub.charges_count} charges)</span>
                      </span>
                      <span className="num font-medium text-amber-300">
                        {formatCurrency(sub.monthly_avg, currency)}/mo (
                        {formatCurrency(sub.annualized_cost, currency)}/yr)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
