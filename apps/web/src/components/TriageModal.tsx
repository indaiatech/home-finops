import { Check, X } from "lucide-react";
import { useEffect, useState } from "react";
import {
  api,
  type CategoryTree,
  type Person,
  type TransactionItem,
  formatCurrency,
} from "../api";

interface TriageModalProps {
  people: Person[];
  categories: CategoryTree[];
  currency: string;
  onClose: () => void;
  onUpdated: () => void;
}

export function TriageModal({
  people,
  categories,
  currency,
  onClose,
  onUpdated,
}: TriageModalProps) {
  const [txs, setTxs] = useState<TransactionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [drafts, setDrafts] = useState<
    Record<string, { category_id: string; scope: "shared" | "personal"; owner: string }>
  >({});

  async function load() {
    setLoading(true);
    try {
      const res = await api.listUncategorized();
      setTxs(res.transactions);
      const nextDrafts: Record<
        string,
        { category_id: string; scope: "shared" | "personal"; owner: string }
      > = {};
      const defaultCat = categories[1]?.subcategories[0]?.id || categories[0]?.subcategories[0]?.id || "";
      for (const tx of res.transactions) {
        nextDrafts[tx.id] = {
          category_id: defaultCat,
          scope: tx.scope,
          owner: tx.owner_person_id || tx.paid_by_person_id || people[0]?.id || "",
        };
      }
      setDrafts(nextDrafts);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function saveOne(txId: string) {
    const d = drafts[txId];
    if (!d?.category_id) return;
    await api.patchTransaction(txId, {
      category_id: d.category_id,
      scope: d.scope,
      owner_person_id: d.scope === "personal" ? d.owner : null,
    });
    setTxs((prev) => prev.filter((t) => t.id !== txId));
    onUpdated();
  }

  async function markTransfer(txId: string) {
    await api.patchTransaction(txId, { is_internal_transfer: true });
    setTxs((prev) => prev.filter((t) => t.id !== txId));
    onUpdated();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs">
      <div className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-white">Uncategorized Transaction Triage</h2>
            <p className="text-xs text-slate-400">
              Assign a category and scope (General vs. Personal) or mark as an internal transfer.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="text-sm text-slate-400">Loading uncategorized items...</div>
          ) : txs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-emerald-800/60 bg-emerald-950/20 p-8 text-center text-sm text-emerald-300">
              All transactions are categorized!
            </div>
          ) : (
            <div className="space-y-3">
              {txs.map((tx) => {
                const draft = drafts[tx.id];
                if (!draft) return null;
                return (
                  <div
                    key={tx.id}
                    className="grid grid-cols-1 items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3 md:grid-cols-12"
                  >
                    <div className="md:col-span-4">
                      <div className="truncate text-sm font-medium text-white">{tx.description}</div>
                      <div className="mt-0.5 text-xs text-slate-400">
                        {tx.date} • paid by {tx.paid_by_person_id} •{" "}
                        <span className="num font-semibold text-amber-300">
                          {formatCurrency(Math.abs(tx.amount), currency)}
                        </span>
                      </div>
                    </div>

                    <div className="md:col-span-3">
                      <select
                        value={draft.category_id}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [tx.id]: { ...prev[tx.id], category_id: e.target.value },
                          }))
                        }
                        className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-white"
                      >
                        {categories.map((cat) => (
                          <optgroup key={cat.id} label={cat.name}>
                            {cat.subcategories.map((sub) => (
                              <option key={sub.id} value={sub.id}>
                                {sub.name}
                              </option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    </div>

                    <div className="flex gap-1.5 md:col-span-3">
                      <select
                        value={draft.scope}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [tx.id]: {
                              ...prev[tx.id],
                              scope: e.target.value as "shared" | "personal",
                            },
                          }))
                        }
                        className="w-1/2 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
                      >
                        <option value="shared">General</option>
                        <option value="personal">Personal</option>
                      </select>

                      {draft.scope === "personal" && (
                        <select
                          value={draft.owner}
                          onChange={(e) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [tx.id]: { ...prev[tx.id], owner: e.target.value },
                            }))
                          }
                          className="w-1/2 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
                        >
                          {people.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.display_name}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>

                    <div className="flex justify-end gap-1.5 md:col-span-2">
                      <button
                        onClick={() => markTransfer(tx.id)}
                        title="Exclude as internal transfer"
                        className="rounded-lg border border-slate-700 px-2 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800"
                      >
                        Transfer
                      </button>
                      <button
                        onClick={() => saveOne(tx.id)}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500"
                      >
                        <Check className="h-3.5 w-3.5" /> Save
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
