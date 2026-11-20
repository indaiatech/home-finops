"""Export the 24-month FinOps spreadsheet matrix to CSV or formatted XLSX."""

from __future__ import annotations

import csv
import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


def export_matrix_csv(matrix: dict[str, Any]) -> bytes:
    buf = io.StringIO()
    months: list[str] = matrix["months"]
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Section",
            "Category",
            "Subcategory",
            "Scope",
            "Owner",
            "Annual",
            *months,
            f"Total {matrix['base_year']}",
            f"Total {matrix['next_year']}",
            "Monthly Avg",
        ]
    )

    for row in matrix["rows"]:
        writer.writerow(
            [
                row["section"],
                row["parent_category_name"],
                row["category_name"],
                row["scope"],
                row["owner_display_name"],
                "yes" if row["is_annual"] else "no",
                *[f"{row['cells'][m]['value']:.2f}" for m in months],
                f"{row['total_year_1']:.2f}",
                f"{row['total_year_2']:.2f}",
                f"{row['monthly_avg']:.2f}",
            ]
        )

    return buf.getvalue().encode("utf-8")


def export_matrix_xlsx(matrix: dict[str, Any]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = f"FinOps {matrix['base_year']}-{matrix['next_year']}"
    months: list[str] = matrix["months"]

    headers = [
        "Section",
        "Category",
        "Subcategory",
        "Scope",
        "Owner",
        *months,
        f"Total {matrix['base_year']}",
        f"Total {matrix['next_year']}",
        "Monthly Avg",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font

    for row in matrix["rows"]:
        ws.append(
            [
                row["section"].title(),
                row["parent_category_name"],
                row["category_name"],
                row["scope"].title(),
                row["owner_display_name"],
                *[row["cells"][m]["value"] for m in months],
                row["total_year_1"],
                row["total_year_2"],
                row["monthly_avg"],
            ]
        )

    # Summary rows
    ws.append([])
    for label, key in (
        ("Total Income", "income"),
        ("Total Expenses", "expenses"),
        ("Net Cash Flow", "net_cashflow"),
        ("Projected Balance", "projected_balance"),
    ):
        ws.append(
            [
                "Summary",
                label,
                "",
                "",
                "",
                *[matrix["summary"][m][key] for m in months],
                "",
                "",
                "",
            ]
        )
        for col_idx in range(1, len(headers) + 1):
            ws.cell(row=ws.max_row, column=col_idx).font = Font(bold=True)

    # Apply number formatting to numeric columns
    for r_idx in range(2, ws.max_row + 1):
        for c_idx in range(6, len(headers) + 1):
            c = ws.cell(row=r_idx, column=c_idx)
            if isinstance(c.value, (int, float)):
                c.number_format = "#,##0.00"

    ws.freeze_panes = "F2"

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
