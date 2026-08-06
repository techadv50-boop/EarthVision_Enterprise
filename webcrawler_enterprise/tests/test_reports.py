"""Folder and report tests."""

from pathlib import Path

from webcrawler.crawler.site_crawler import SiteResult
from webcrawler.reports.generator import append_master_report, write_summary
from webcrawler.utils.folders import ensure_site_structure, html_mirror_path, site_folder


def test_site_folder_structure(tmp_path: Path):
    folder = site_folder(tmp_path, "https://www.nasa.gov/missions")
    ensure_site_structure(folder)
    assert folder.name == "nasa.gov"
    for name in ("PDF", "Word", "Excel", "PowerPoint", "Images", "HTML", "Reports", "Logs"):
        assert (folder / name).is_dir()


def test_html_mirror_path(tmp_path: Path):
    folder = ensure_site_structure(site_folder(tmp_path, "https://qau.edu.pk"))
    path = html_mirror_path(folder, "https://qau.edu.pk/contact-list/")
    assert path.name == "index.html"
    assert "contact-list" in str(path)
    assert path.parent.exists()


def test_reports(tmp_path: Path):
    site_dir = ensure_site_structure(site_folder(tmp_path, "https://mit.edu"))
    result = SiteResult(
        website="https://mit.edu",
        domain="mit.edu",
        pages_crawled=3,
        documents_downloaded=1,
        pdfs=1,
        emails=2,
        phones=1,
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:01:00+00:00",
        processing_time="0:01:00",
        status="Completed",
        site_dir=site_dir,
    )
    summary = write_summary(result)
    assert summary.exists()
    assert "Total Pages Crawled: 3" in summary.read_text(encoding="utf-8")
    master = append_master_report(tmp_path, result)
    assert master.exists()
    append_master_report(tmp_path, result)
    assert master.stat().st_size > 0
