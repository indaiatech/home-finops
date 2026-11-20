import { Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import {
  api,
  type CellBreakdown,
  type SpreadsheetRow,
  formatCurrency,
  formatMonthShort,
} from "../api";

interface CellDrawerProps {
  row: SpreadsheetRow;
  month: string;
  currency: string;
  annualMode: "cash" | "monthly_provision";
  currentMonth: string;
  onClose: () => void;
  onUpdated: () => void;
}

export function CellDrawer({
  row,
  month,
  currency,
  annualMode,
  currentMonth,
  onClose,
  onUpdated,
}: CellDrawerProps) {
  const [data, setData] = useState<CellBreakdown | null>(null);
  const [loading, setLoading] = useState(true);
  const [overrideAmount, setOverrideAmount] = useState("");
  const [overrideNote, setOverrideNote] = useState("");
  const [saving, setSaving] = useState(false);

  const cell = row.cells[month];
  const isEditable = month >= currentMonth && row.category_id !== "uncategorized";

  useEffect(() => {
    let active = true;
    setLoading(true);
    api
      .getCellBreakdown({
        month,
        category_id: row.category_id,
        scope: row.scope,
        owner_person_id: row.owner_person_id,
        annual_mode: annualMode,
      })
      .then((res) => {
        if (!active) return;
        setData(res);
        setOverrideAmount(String(res.override ? res.override.amount : cell.value));
        setOverrideNote(res.override?.note || "");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [month, row.category_id, row.scope, row.owner_person_id, annualMode, cell.value]);

  async function handleSaveOverride(e: React.FormEvent) {
    e.preventDefault();
    const num = Number(overrideAmount);
    if (Number.isNaN(num) || num < 0) return;
    setSaving(true);
    try {
      await api.upsertOverride({
        competence_month: month,
        category_id: row.category_id,
        scope: row.scope,
        owner_person_id: row.owner_person_id,
        amount: num,
        note: overrideNote.trim() || undefined,
      });
      onUpdated();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  async function handleClearOverride() {
    setSaving(true);
    try {
      await api.deleteOverride({
        month,
        category_id: row.category_id,
        scope: row.scope,
        owner_person_id: row.owner_person_id,
      });
      onUpdated();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-slate-800 bg-slate-900 shadow-2xl">
      <div className="flex items-start justify-between border-b border-slate-800 px-5 py-4">
        <div>
          <div className="text-xs font-medium uppercase tracking-wider text-emerald-400">
            {formatMonthShort(month)} • {row.scope === "shared" ? "General (Shared)" : row.owner_display_name}
          </div>
          <h2 className="mt-0.5 text-lg font-semibold text-white">
            {row.parent_category_name} / {row.category_name}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-5">
        {/* Cell Metrics */}
        <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
          <div>
            <div className="text-[11px] text-slate-400">Displayed</div>
            <div className="num mt-0.5 text-sm font-semibold text-white">
              {formatCurrency(cell.value, currency)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-slate-400">Realized</div>
            <div className="num mt-0.5 text-sm font-semibold text-emerald-400">
              {formatCurrency(cell.realized, currency)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-slate-400">Auto-Projected</div>
            <div className="num mt-0.5 text-sm font-semibold text-sky-400">
              {formatCurrency(cell.projected, currency)}
            </div>
          </div>
        </div>

        {/* Manual Override Editor */}
        {isEditable && (
          <form
            onSubmit={handleSaveOverride}
            className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/50 p-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-amber-400">
                Manual Projection Override
              </h3>
              {data?.override && (
                <button
                  type="button"
                  onClick={handleClearOverride}
                  disabled={saving}
                  className="inline-flex items-center gap-1 text-xs text-rose-400 hover:text-rose-300"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Reset to Auto
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 gap-2">
              <label className="text-xs text-slate-400">
                Amount ({currency})
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={overrideAmount}
                  onChange={(e) => setOverrideAmount(e.target.value)}
                  className="num mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white focus:border-emerald-500 focus:outline-none"
                />
              </label>
              <label className="text-xs text-slate-400">
                Note (optional)
                <input
                  type="text"
                  placeholder="e.g., Holiday travel budget"
                  value={overrideNote}
                  onChange={(e) => setOverrideNote(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white focus:border-emerald-500 focus:outline-none"
                />
              </label>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="w-full rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save Override"}
            </button>
          </form>
        )}

        {/* Active Projection Rules */}
        {loading ? (
          <div className="text-sm text-slate-400">Loading cell breakdown...</div>
        ) : (
          <>
            {data && data.projection_rules.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  YAML Projection Rules ({data.projection_rules.length})
                </h3>
                <div className="space-y-1.5">
                  {data.projection_rules.map((r) => (
                    <div
                      key={r.id}
                      className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs"
                    >
                      <div>
                        <div className="font-medium text-slate-200">{r.name}</div>
                        <div className="text-[11px] text-slate-400">
                          {r.rule_kind} • {r.frequency}
                        </div>
                      </div>
                      <div className="num font-semibold text-sky-400">
                        {formatCurrency(r.amount, currency)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Realized Transactions */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Realized Transactions ({data?.transactions.length ?? 0})
              </h3>
              {data && data.transactions.length > 0 ? (
                <div className="space-y-1.5">
                  {data.transactions.map((tx) => (
                    <div
                      key={tx.id}
                      className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs"
                    >
                      <div className="min-w-0 pr-3">
                        <div className="truncate font-medium text-slate-200">{tx.description}</div>
                        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                          <span>{tx.date}</span>
                          <span>• paid by {tx.paid_by_person_id}</span>
                          {tx.installment && (
                            <span className="rounded bg-indigo-500/20 px-1.5 py-0.5 text-[10px] text-indigo-300">
                              {tx.installment}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="num shrink-0 font-semibold text-slate-100">
                        {formatCurrency(Math.abs(tx.amount), currency)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-800 p-4 text-center text-xs text-slate-500">
                  No realized transactions in this cell.
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
