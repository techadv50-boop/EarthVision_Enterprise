"""Report generation: PDF, Excel, CSV."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


class ReportService:
    def generate_pdf(self, title: str, sections: list[dict[str, Any]]) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, title=title)
        styles = getSampleStyleSheet()
        story: list[Any] = []
        story.append(Paragraph("SAT EYE — Eye In Sky", styles["Title"]))
        story.append(Paragraph(title, styles["Heading1"]))
        story.append(
            Paragraph(
                f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.5 * cm))

        for section in sections:
            story.append(Paragraph(section.get("heading", "Section"), styles["Heading2"]))
            if section.get("body"):
                story.append(Paragraph(str(section["body"]), styles["Normal"]))
            if section.get("table"):
                data = section["table"]
                table = Table(data, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D2E")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.97, 0.95)]),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.append(table)
            story.append(Spacer(1, 0.4 * cm))

        doc.build(story)
        return buffer.getvalue()

    def generate_excel(self, sheets: dict[str, list[list[Any]]]) -> bytes:
        wb = Workbook()
        first = True
        for name, rows in sheets.items():
            if first:
                ws = wb.active
                ws.title = name[:31]
                first = False
            else:
                ws = wb.create_sheet(title=name[:31])
            for row in rows:
                ws.append(row)
        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def generate_csv(self, rows: list[list[Any]]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().encode("utf-8")
