# WebCrawler Enterprise

Professional Windows desktop application that crawls websites sequentially, downloads documents, extracts emails and phone numbers, and writes structured reports.

## Features

- Login account (`admin` / `admin`) with required password change on first login
- Master reset code `NTZHSS` restores the admin account
- Multiline URL input with blank-line ignore and automatic deduplication
- Sequential multi-site processing (one website at a time)
- **Complete website download** (all reachable pages, documents, images)
- **High-speed parallel crawl** (many pages/downloads at once; Playwright only as fallback)
- Sitemap discovery + contact-page prioritization
- Document download: PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX, CSV, TXT, ZIP
- Duplicate prevention via URL + SHA-256
- Email and phone extraction from every HTML page and document
- Per-site folders (`PDF`, `Word`, `Excel`, `PowerPoint`, `Images`, `HTML`, `Reports`, `Logs`)
- Always writes `emails.txt` and `phone_numbers.txt` (plus copies in `Reports/`)
- `Reports/Summary.txt`, `Reports/pages_index.txt`, `Logs/crawl_log.txt`
- Root `Master_Report.xlsx` appended after each site
- SQLite queue with Pending / Running / Completed / Failed / Cancelled and crash resume
- Persisted URL frontier: survives power loss, PC reboot, and internet disconnects
- Broken / 404 URLs are skipped; crawl continues to the next page
- Auto-offers Resume on startup when unfinished websites remain
- Configurable settings persisted automatically
- Start / Pause / Resume / Stop controls with live progress

## Login

| Item | Value |
|------|-------|
| Username | `admin` |
| Default password | `admin` |
| First login | Must change password before using the app |
| Master reset code | `NTZHSS` (Login screen → **Master Reset…**) |

Master reset restores username `admin`, password `admin`, admin role, and requires a password change again.

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
| `gui` | PySide6 UI, login, progress, settings |
| `auth` | Login, password change, master reset |
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
- One website is processed at a time. Page rendering is sequential (Playwright-safe); downloads use worker threads.
- The crawler prioritizes contact/faculty pages, reads sitemaps, and falls back to HTTP when rendering is thin.
- Phone parsing uses country hints from the domain (e.g. `.pk` → Pakistan).
- Failed sites are logged and processing continues with the next URL.

## Re-crawl tip

If an earlier run saved empty `emails.txt` / `phone_numbers.txt`, delete that website folder (or clear the app SQLite DB under `%APPDATA%\WebCrawlerEnterprise`) before starting again so pages are not skipped as already visited.
