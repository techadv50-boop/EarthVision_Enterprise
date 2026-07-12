"""Report generation service (PDF, Excel, CSV)."""

import csv
import io
import json
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import get_settings


class ReportService:
    def __init__(self):
        self.settings = get_settings()
        self.output_dir = self.settings.upload_dir / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_pdf(self, title: str, content: dict[str, Any]) -> str:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        output_path = self.output_dir / f"{title.replace(' ', '_')}.pdf"
        doc = SimpleDocTemplate(str(output_path), pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(title, styles["Title"]))
        elements.append(Spacer(1, 20))

        if "statistics" in content:
            stats = content["statistics"]
            data = [["Metric", "Value"]] + [[k, str(v)] for k, v in stats.items()]
            table = Table(data, colWidths=[200, 200])
            table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ])
            )
            elements.append(table)

        if "summary" in content:
            elements.append(Spacer(1, 20))
            elements.append(Paragraph(content["summary"], styles["Normal"]))

        doc.build(elements)
        return str(output_path)

    def generate_excel(self, title: str, content: dict[str, Any]) -> str:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        output_path = self.output_dir / f"{title.replace(' ', '_')}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Report"

        ws["A1"] = title
        ws["A1"].font = Font(size=16, bold=True)

        row = 3
        if "statistics" in content:
            ws.cell(row=row, column=1, value="Metric").font = Font(bold=True)
            ws.cell(row=row, column=2, value="Value").font = Font(bold=True)
            header_fill = PatternFill(start_color="1e40af", end_color="1e40af", fill_type="solid")
            ws.cell(row=row, column=1).fill = header_fill
            ws.cell(row=row, column=2).fill = header_fill
            row += 1
            for key, value in content["statistics"].items():
                ws.cell(row=row, column=1, value=key)
                ws.cell(row=row, column=2, value=value)
                row += 1

        if "time_series" in content:
            row += 2
            ws.cell(row=row, column=1, value="Date").font = Font(bold=True)
            ws.cell(row=row, column=2, value="Value").font = Font(bold=True)
            row += 1
            for point in content["time_series"]:
                ws.cell(row=row, column=1, value=str(point.get("date", "")))
                ws.cell(row=row, column=2, value=point.get("value", 0))
                row += 1

        wb.save(output_path)
        return str(output_path)

    def generate_csv(self, title: str, content: dict[str, Any]) -> str:
        output_path = self.output_dir / f"{title.replace(' ', '_')}.csv"

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([title])
            writer.writerow([])

            if "statistics" in content:
                writer.writerow(["Metric", "Value"])
                for key, value in content["statistics"].items():
                    writer.writerow([key, value])
                writer.writerow([])

            if "time_series" in content:
                writer.writerow(["Date", "Value", "Scene ID"])
                for point in content["time_series"]:
                    writer.writerow([
                        point.get("date", ""),
                        point.get("value", 0),
                        point.get("scene_id", ""),
                    ])

        return str(output_path)
