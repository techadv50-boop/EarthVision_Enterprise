# WebCrawler Enterprise

Professional Windows desktop application that crawls websites sequentially, downloads documents, extracts emails and phone numbers, and writes structured reports.

## Features

- Multiline URL input with blank-line ignore and automatic deduplication
- Sequential multi-site processing (one website at a time)
- Playwright-based rendering (JavaScript executed before extraction)
- Internal-link crawling with depth/max-page limits and duplicate/loop protection
- Document download: PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX, CSV, TXT, ZIP
- Duplicate prevention via URL + SHA-256
- Email and phone extraction from HTML and documents
- Per-site folders (`PDF`, `Word`, `Excel`, `PowerPoint`, `Images`, `HTML`, `Reports`, `Logs`)
- `emails.txt`, `phone_numbers.txt`, `Reports/Summary.txt`, `Logs/crawl_log.txt`
- Root `Master_Report.xlsx` appended after each site
- SQLite queue with Pending / Running / Completed / Failed / Cancelled and crash resume
- Configurable settings persisted automatically
- Start / Pause / Resume / Stop controls with live progress

## Requirements

- Python 3.11+ (developed for Python 3.13)
- Windows 10/11 recommended for the packaged `.exe` (also runs on Linux/macOS for development)

## Setup

```bash
cd webcrawler_enterprise
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## Run

```bash
python main.py
```

## Tests

```bash
pytest -q
```

## Package for Windows

```bash
pip install pyinstaller
playwright install chromium
pyinstaller --noconfirm webcrawler_enterprise.spec
```

Output: `dist/WebCrawlerEnterprise/WebCrawlerEnterprise.exe`

> Playwright browser binaries must be available on the target machine (bundled via the installer or installed with `playwright install chromium`).

## Architecture

| Package | Role |
|---------|------|
| `gui` | PySide6 UI, progress, settings |
| `engine` | Orchestrates sequential site processing |
| `queue` | URL queue states + resume |
| `crawler` | Playwright site crawler |
| `parser` | BeautifulSoup HTML parsing |
| `downloader` | httpx downloads + hashing |
| `extractors` | Email / phone extraction |
| `reports` | Summary + Master_Report.xlsx |
| `db` | SQLite metadata |
| `settings` | Persisted configuration |
| `logger` | Crawl logging |

## Output layout

```
D:\WebsiteData\
  Master_Report.xlsx
  harvard.edu\
    PDF\
    Word\
    Excel\
    PowerPoint\
    Images\
    HTML\
    Reports\Summary.txt
    Logs\crawl_log.txt
    emails.txt
    phone_numbers.txt
```

## Notes

- Respect website terms of service and applicable laws. Prefer leaving **Ignore robots.txt** disabled.
- One website is processed at a time; pages within a site use configurable worker concurrency.
- Failed sites are logged and processing continues with the next URL.
