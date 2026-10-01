from app.models import ArticleMeta
from app.report import build_summary, failed_entries, format_report_text


def test_failed_entries_and_report():
    metas = [
        ArticleMeta(doi="10.1/ok", title="Ok"),
        ArticleMeta(doi="10.1/bad", error="DOI landing page returned HTTP 404 (not found)"),
    ]
    failed = failed_entries(metas)
    assert len(failed) == 1
    assert failed[0]["doi"] == "10.1/bad"
    summary = build_summary(total=2, succeeded=1, failed=1, failed_dois=failed)
    text = format_report_text(summary)
    assert "Succeeded (done)   : 1" in text
    assert "Failed (not done)  : 1" in text
    assert "10.1/bad" in text
    assert "HTTP 404" in text
