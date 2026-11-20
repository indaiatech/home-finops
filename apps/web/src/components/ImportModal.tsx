import { Upload, X } from "lucide-react";
import { useState } from "react";
import { api, type Person } from "../api";

interface ImportModalProps {
  people: Person[];
  onClose: () => void;
  onImported: () => void;
}

export function ImportModal({ people, onClose, onImported }: ImportModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [personId, setPersonId] = useState(people[0]?.id || "person_a");
  const [accountName, setAccountName] = useState("Bank Statement");
  const [scope, setScope] = useState<"personal" | "shared">("personal");
  const [status, setStatus] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setStatus(null);
    try {
      const res = await api.uploadStatement(file, personId, accountName, scope);
      setStatus(
        `Imported ${res.inserted} new transactions (${res.skipped_duplicates} duplicates skipped).`
      );
      onImported();
    } catch (err) {
      setStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Import CSV / OFX Statement</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400">Household Member</label>
            <select
              value={personId}
              onChange={(e) => setPersonId(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
            >
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-400">Account Label</label>
              <input
                type="text"
                value={accountName}
                onChange={(e) => setAccountName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400">Default Scope</label>
              <select
                value={scope}
                onChange={(e) => setScope(e.target.value as "personal" | "shared")}
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
              >
                <option value="personal">Personal</option>
                <option value="shared">General (Shared)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs text-slate-400">Statement File (.csv or .ofx)</label>
            <input
              type="file"
              accept=".csv,.ofx,.qfx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 file:mr-3 file:rounded-md file:border-0 file:bg-emerald-600 file:px-3 file:py-1 file:text-xs file:font-semibold file:text-white"
            />
          </div>

          {status && (
            <div className="rounded-lg border border-slate-700 bg-slate-950 p-3 text-xs text-slate-200">
              {status}
            </div>
          )}

          <button
            type="submit"
            disabled={!file || uploading}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            <Upload className="h-4 w-4" />
            {uploading ? "Importing..." : "Upload & Deduplicate"}
          </button>
        </form>
      </div>
    </div>
  );
}
