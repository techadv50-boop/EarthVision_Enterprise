"""Report generation routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportRequest(BaseModel):
    title: str = "EarthVision Analysis Report"
    format: str = Field(default="pdf", pattern="^(pdf|excel|csv)$")
    sections: list[dict] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)


@router.post("/generate")
async def generate_report(data: ReportRequest, user: CurrentUser) -> Response:
    service = ReportService()
    if data.format == "pdf":
        content = service.generate_pdf(data.title, data.sections or [
            {
                "heading": "Summary",
                "body": f"Report generated for {user.email}",
                "table": [["Metric", "Value"], ["User", user.full_name], ["Role", user.role.value]],
            }
        ])
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="earthvision-report.pdf"'},
        )
    if data.format == "excel":
        sheets = {"Report": data.rows or [["Metric", "Value"], ["Platform", "EarthVision Enterprise"]]}
        content = service.generate_excel(sheets)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="earthvision-report.xlsx"'},
        )
    content = service.generate_csv(data.rows or [["Metric", "Value"], ["Platform", "EarthVision"]])
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="earthvision-report.csv"'},
    )
