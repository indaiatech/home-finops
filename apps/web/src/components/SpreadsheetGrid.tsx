import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type SpreadsheetMatrix,
  type SpreadsheetRow,
  formatCurrency,
  formatMonthShort,
} from "../api";

interface SpreadsheetGridProps {
  matrix: SpreadsheetMatrix;
  visibleMonths: string[];
  onSelectCell: (row: SpreadsheetRow, month: string) => void;
  onOverrideSaved: () => void;
}

const SECTION_META: Record<
  SpreadsheetRow["section"],
  { title: string; badgeClass: string; order: number }
> = {
  income: {
    title: "Income",
    badgeClass: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    order: 0,
  },
  shared: {
    title: "General / Shared Expenses",
    badgeClass: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    order: 1,
  },
  annual: {
    title: "Annual & Seasonal Expenses",
    badgeClass: "bg-violet-500/15 text-violet-300 border-violet-500/30",
    order: 2,
  },
  personal: {
    title: "Personal Expenses (By Person)",
    badgeClass: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    order: 3,
  },
  uncategorized: {
    title: "Uncategorized (Needs Triage)",
    badgeClass: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    order: 4,
  },
};

export function SpreadsheetGrid({
  matrix,
  visibleMonths,
  onSelectCell,
  onOverrideSaved,
}: SpreadsheetGridProps) {
  const [collapsedSections, setCollapsedSections] = useState<Record<string, boolean>>({});
  const [editingCell, setEditingCell] = useState<{
    rowId: string;
    month: string;
    value: string;
  } | null>(null);
  const currentMonthColRef = useRef<HTMLTableCellElement | null>(null);

  useEffect(() => {
    currentMonthColRef.current?.scrollIntoView({
      behavior: "smooth",
      inline: "center",
      block: "nearest",
    });
  }, [matrix.base_year, visibleMonths.length]);

  const sections = useMemo(() => {
    const grouped: Record<string, SpreadsheetRow[]> = {};
    for (const r of matrix.rows) {
      grouped[r.section] = grouped[r.section] || [];
      grouped[r.section].push(r);
    }
    return (Object.keys(grouped) as Array<SpreadsheetRow["section"]>).sort(
      (a, b) => SECTION_META[a].order - SECTION_META[b].order
    ).map((sec) => ({
      section: sec,
      rows: grouped[sec],
    }));
  }, [matrix.rows]);

  async function commitInlineEdit(row: SpreadsheetRow, month: string, rawVal: string) {
    const num = Number(rawVal.replace(",", "."));
    setEditingCell(null);
    if (Number.isNaN(num) || num < 0) return;
    await api.upsertOverride({
      competence_month: month,
      category_id: row.category_id,
      scope: row.scope,
      owner_person_id: row.owner_person_id,
      amount: num,
    });
    onOverrideSaved();
  }

  const columns = useMemo<ColumnDef<SpreadsheetRow>[]>(() => {
    const leftCols: ColumnDef<SpreadsheetRow>[] = [
      {
        id: "label",
        header: () => <span>Category / Subcategory</span>,
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-slate-100">
                  {r.category_name}
                </div>
                <div className="truncate text-[10px] text-slate-400">
                  {r.parent_category_name}
                  {r.scope === "personal" ? ` • ${r.owner_display_name}` : " • General"}
                  {r.is_annual ? " • Annual" : ""}
                </div>
              </div>
            </div>
          );
        },
      },
    ];

    const monthCols: ColumnDef<SpreadsheetRow>[] = visibleMonths.map((mk) => ({
      id: mk,
      header: () => (
        <div className="flex flex-col items-end">
          <span className={mk === matrix.current_month ? "font-bold text-emerald-300" : ""}>
            {formatMonthShort(mk)}
          </span>
          {mk === matrix.current_month && (
            <span className="text-[9px] font-semibold uppercase tracking-wider text-emerald-400">
              Current
            </span>
          )}
        </div>
      ),
      cell: ({ row }) => {
        const r = row.original;
        const cell = r.cells[mk];
        const isEditing = editingCell?.rowId === r.row_id && editingCell?.month === mk;
        const canEdit = mk >= matrix.current_month && r.category_id !== "uncategorized";

        if (isEditing) {
          return (
            <input
              autoFocus
              type="text"
              value={editingCell.value}
              onChange={(e) =>
                setEditingCell((prev) => (prev ? { ...prev, value: e.target.value } : null))
              }
              onBlur={() => commitInlineEdit(r, mk, editingCell.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  commitInlineEdit(r, mk, editingCell.value);
                } else if (e.key === "Escape") {
                  setEditingCell(null);
                }
              }}
              className="num w-24 rounded border border-emerald-400 bg-slate-950 px-1.5 py-0.5 text-right text-xs text-white outline-none"
            />
          );
        }

        const isProjected = cell.source === "projected" || cell.source === "installment";
        const isOverride = cell.source === "override";
        const isZero = cell.value === 0;

        return (
          <div
            onClick={() => onSelectCell(r, mk)}
            onDoubleClick={(e) => {
              e.stopPropagation();
              if (!canEdit) return;
              setEditingCell({ rowId: r.row_id, month: mk, value: String(cell.value) });
            }}
            title={
              cell.note
                ? `Manual override: ${cell.note}`
                : canEdit
                  ? "Click for breakdown • Double-click to override"
                  : "Click to inspect realized transactions"
            }
            className={`num group relative flex cursor-pointer items-center justify-end gap-1 rounded px-1.5 py-1 text-right text-xs transition hover:bg-slate-800/80 ${
              isZero
                ? "text-slate-600"
                : isOverride
                  ? "font-semibold text-amber-300"
                  : isProjected
                    ? "italic text-sky-300/90"
                    : r.kind === "income"
                      ? "font-medium text-emerald-300"
                      : "text-slate-100"
            }`}
          >
            {isOverride && (
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400"
                title="Manual override"
              />
            )}
            {cell.installments > 0 && mk > matrix.current_month && !isOverride && (
              <span
                className="rounded bg-indigo-500/20 px-1 text-[9px] font-medium not-italic text-indigo-300"
                title={`Includes ${formatCurrency(cell.installments, matrix.currency)} in credit-card installments`}
              >
                inst
              </span>
            )}
            <span>{isZero ? "—" : formatCurrency(cell.value, matrix.currency)}</span>
          </div>
        );
      },
    }));

    const summaryCols: ColumnDef<SpreadsheetRow>[] = [
      {
        id: "total_y1",
        header: () => <span>Total {matrix.base_year}</span>,
        cell: ({ row }) => (
          <div className="num text-right text-xs font-semibold text-slate-200">
            {formatCurrency(row.original.total_year_1, matrix.currency)}
          </div>
        ),
      },
      {
        id: "total_y2",
        header: () => <span>Total {matrix.next_year}</span>,
        cell: ({ row }) => (
          <div className="num text-right text-xs font-semibold text-sky-300">
            {formatCurrency(row.original.total_year_2, matrix.currency)}
          </div>
        ),
      },
      {
        id: "avg",
        header: () => <span>Avg / mo</span>,
        cell: ({ row }) => (
          <div className="num text-right text-xs text-slate-400">
            {formatCurrency(row.original.monthly_avg, matrix.currency)}
          </div>
        ),
      },
    ];

    return [...leftCols, ...monthCols, ...summaryCols];
  }, [matrix, visibleMonths, editingCell]);

  const table = useReactTable({
    data: matrix.rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const rowsById = useMemo(() => {
    const map = new Map<string, ReturnType<typeof table.getRowModel>["rows"][number]>();
    for (const tr of table.getRowModel().rows) {
      map.set(tr.original.row_id, tr);
    }
    return map;
  }, [table, matrix.rows]);

  const totalY1Income = matrix.months
    .slice(0, 12)
    .reduce((acc, m) => acc + (matrix.summary[m]?.income || 0), 0);
  const totalY2Income = matrix.months
    .slice(12)
    .reduce((acc, m) => acc + (matrix.summary[m]?.income || 0), 0);
  const totalY1Exp = matrix.months
    .slice(0, 12)
    .reduce((acc, m) => acc + (matrix.summary[m]?.expenses || 0), 0);
  const totalY2Exp = matrix.months
    .slice(12)
    .reduce((acc, m) => acc + (matrix.summary[m]?.expenses || 0), 0);

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900/70 shadow-xl">
      <div className="max-h-[64vh] overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-left">
          <thead className="sticky top-0 z-20 bg-slate-950">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((header, idx) => {
                  const isStickyLeft = idx === 0;
                  const isCurrent = header.id === matrix.current_month;
                  return (
                    <th
                      key={header.id}
                      ref={isCurrent ? currentMonthColRef : undefined}
                      className={`border-b border-r border-slate-800 px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-300 ${
                        isStickyLeft
                          ? "sticky left-0 z-30 min-w-[230px] bg-slate-950 text-left"
                          : "min-w-[116px] text-right"
                      } ${isCurrent ? "bg-emerald-950/50 border-x-emerald-700/60" : ""}`}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>

          <tbody>
            {sections.map(({ section, rows }) => {
              const meta = SECTION_META[section];
              const isCollapsed = !!collapsedSections[section];
              return (
                <Fragment key={section}>
                  <tr
                    onClick={() =>
                      setCollapsedSections((prev) => ({ ...prev, [section]: !prev[section] }))
                    }
                    className="cursor-pointer bg-slate-950/85 hover:bg-slate-900"
                  >
                    <td
                      className="sticky left-0 z-10 border-b border-r border-slate-800 bg-slate-950/95 px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        {isCollapsed ? (
                          <ChevronRight className="h-4 w-4 text-slate-400" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-slate-400" />
                        )}
                        <span
                          className={`rounded-md border px-2 py-0.5 text-[11px] font-semibold ${meta.badgeClass}`}
                        >
                          {meta.title}
                        </span>
                        <span className="text-[11px] text-slate-500">({rows.length})</span>
                      </div>
                    </td>
                    {visibleMonths.map((mk) => {
                      const secTotal = rows.reduce((acc, r) => acc + (r.cells[mk]?.value || 0), 0);
                      return (
                        <td
                          key={mk}
                          className={`num border-b border-r border-slate-800/70 px-3 py-2 text-right text-[11px] font-semibold text-slate-400 ${
                            mk === matrix.current_month ? "bg-emerald-950/25" : ""
                          }`}
                        >
                          {secTotal > 0 ? formatCurrency(secTotal, matrix.currency) : "—"}
                        </td>
                      );
                    })}
                    <td className="num border-b border-r border-slate-800 px-3 py-2 text-right text-[11px] font-semibold text-slate-300">
                      {formatCurrency(
                        rows.reduce((a, r) => a + r.total_year_1, 0),
                        matrix.currency
                      )}
                    </td>
                    <td className="num border-b border-r border-slate-800 px-3 py-2 text-right text-[11px] font-semibold text-sky-300">
                      {formatCurrency(
                        rows.reduce((a, r) => a + r.total_year_2, 0),
                        matrix.currency
                      )}
                    </td>
                    <td className="num border-b border-slate-800 px-3 py-2 text-right text-[11px] text-slate-500">
                      {formatCurrency(
                        rows.reduce((a, r) => a + r.monthly_avg, 0),
                        matrix.currency
                      )}
                    </td>
                  </tr>

                  {!isCollapsed &&
                    rows.map((r) => {
                      const tr = rowsById.get(r.row_id);
                      if (!tr) return null;
                      return (
                        <tr key={r.row_id} className="hover:bg-slate-800/35">
                          {tr.getVisibleCells().map((cell, idx) => {
                            const isStickyLeft = idx === 0;
                            const isCurrent = cell.column.id === matrix.current_month;
                            return (
                              <td
                                key={cell.id}
                                className={`border-b border-r border-slate-800/70 px-2.5 py-1.5 ${
                                  isStickyLeft
                                    ? "sticky left-0 z-10 bg-slate-900/95"
                                    : ""
                                } ${isCurrent ? "bg-emerald-950/20" : ""}`}
                              >
                                {flexRender(cell.column.columnDef.cell, cell.getContext())}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                </Fragment>
              );
            })}
          </tbody>

          {/* Sticky Summary Footer */}
          <tfoot className="sticky bottom-0 z-20 bg-slate-950 shadow-[0_-4px_12px_rgba(0,0,0,0.45)]">
            <tr>
              <td className="sticky left-0 z-30 border-t-2 border-r border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold text-emerald-400">
                Total Income
              </td>
              {visibleMonths.map((mk) => (
                <td
                  key={mk}
                  className="num border-t-2 border-r border-slate-700 px-3 py-2 text-right text-xs font-bold text-emerald-400"
                >
                  {formatCurrency(matrix.summary[mk]?.income || 0, matrix.currency)}
                </td>
              ))}
              <td className="num border-t-2 border-r border-slate-700 px-3 py-2 text-right text-xs font-bold text-emerald-400">
                {formatCurrency(totalY1Income, matrix.currency)}
              </td>
              <td className="num border-t-2 border-r border-slate-700 px-3 py-2 text-right text-xs font-bold text-emerald-400">
                {formatCurrency(totalY2Income, matrix.currency)}
              </td>
              <td className="num border-t-2 border-slate-700 px-3 py-2 text-right text-xs font-semibold text-emerald-400/80">
                {formatCurrency((totalY1Income + totalY2Income) / 24, matrix.currency)}
              </td>
            </tr>

            <tr>
              <td className="sticky left-0 z-30 border-t border-r border-slate-800 bg-slate-950 px-3 py-2 text-xs font-bold text-rose-400">
                Total Expenses
              </td>
              {visibleMonths.map((mk) => (
                <td
                  key={mk}
                  className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold text-rose-400"
                >
                  {formatCurrency(matrix.summary[mk]?.expenses || 0, matrix.currency)}
                </td>
              ))}
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold text-rose-400">
                {formatCurrency(totalY1Exp, matrix.currency)}
              </td>
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold text-rose-400">
                {formatCurrency(totalY2Exp, matrix.currency)}
              </td>
              <td className="num border-t border-slate-800 px-3 py-2 text-right text-xs font-semibold text-rose-400/80">
                {formatCurrency((totalY1Exp + totalY2Exp) / 24, matrix.currency)}
              </td>
            </tr>

            <tr>
              <td className="sticky left-0 z-30 border-t border-r border-slate-800 bg-slate-950 px-3 py-2 text-xs font-bold text-white">
                Net Cash Flow
              </td>
              {visibleMonths.map((mk) => {
                const net = matrix.summary[mk]?.net_cashflow || 0;
                return (
                  <td
                    key={mk}
                    className={`num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold ${
                      net >= 0 ? "text-emerald-300" : "text-rose-400"
                    }`}
                  >
                    {formatCurrency(net, matrix.currency)}
                  </td>
                );
              })}
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold text-white">
                {formatCurrency(totalY1Income - totalY1Exp, matrix.currency)}
              </td>
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-bold text-white">
                {formatCurrency(totalY2Income - totalY2Exp, matrix.currency)}
              </td>
              <td className="num border-t border-slate-800 px-3 py-2 text-right text-xs font-semibold text-slate-300">
                {formatCurrency(
                  (totalY1Income + totalY2Income - totalY1Exp - totalY2Exp) / 24,
                  matrix.currency
                )}
              </td>
            </tr>

            <tr>
              <td className="sticky left-0 z-30 border-t border-r border-slate-800 bg-slate-950 px-3 py-2 text-xs font-semibold text-sky-300">
                Projected Balance
              </td>
              {visibleMonths.map((mk) => (
                <td
                  key={mk}
                  className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-semibold text-sky-300"
                >
                  {formatCurrency(matrix.summary[mk]?.projected_balance || 0, matrix.currency)}
                </td>
              ))}
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs text-slate-500">
                —
              </td>
              <td className="num border-t border-r border-slate-800 px-3 py-2 text-right text-xs font-semibold text-sky-300">
                {formatCurrency(
                  matrix.summary[matrix.months[matrix.months.length - 1]]?.projected_balance || 0,
                  matrix.currency
                )}
              </td>
              <td className="num border-t border-slate-800 px-3 py-2 text-right text-xs text-slate-500">
                —
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
