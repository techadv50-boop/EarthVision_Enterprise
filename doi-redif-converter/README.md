# DOI → ReDIF Converter

Web app and CLI that take a list of DOIs, open each DOI landing page (with Crossref enrichment), extract article metadata, and export one **ReDIF-Article 1.0** file per DOI — matching the IJIST / RePEc style used in files like `V8i3p1429-1448.redif`.

## Features

- Paste DOIs or upload `.xlsx` / `.txt` / `.csv`
- Extracts authors, affiliations, title, abstract, keywords, journal, volume, issue, pages, year, month, DOI, and file URLs
- Writes one `.redif` file per DOI (`V{volume}i{issue}p{pages}.redif`)
- Download all results as a ZIP
- Configurable RePEc handle prefix (default `RePEc:abq:IJIST1`)

## Quick start

```bash
cd doi-redif-converter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Web UI
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

### CLI

```bash
# From a DOI list Excel file
python -m app.cli -i samples/DOI_Record.xlsx -o redif_out

# From pasted DOIs
python -m app.cli --dois https://doi.org/10.33411/IJIST/1936 10.33411/IJIST/20190101011
```

## API

| Endpoint | Description |
|----------|-------------|
| `POST /api/parse-upload` | Parse DOIs from uploaded file |
| `POST /api/convert` | Extract metadata + return ReDIF text preview |
| `POST /api/convert-upload` | Convert from uploaded file |
| `POST /api/export-zip` | Extract and download ZIP of `.redif` files |

## Output format

```
Template-Type: ReDIF-Article 1.0
Author-Name:...
Author-Workplace-Name:...
Title:...
Abstract:...
Keywords:...
Journal:...
Pages:...
Volume:...
Issue:...
Year:...
Month:...
DOI:https://doi.org/...
File-URL:...
File-Format: Application/pdf
File-URL:...
File-Format: text/html
Handle: RePEc:abq:IJIST1:v:...:y:...:i:...:p:...
```

## Notes

- Primary metadata source is the DOI landing page (OJS citation meta tags for IJIST).
- Missing fields are filled from the Crossref API.
- Author emails are included only when publicly available on the page or in Crossref.
- Large batches (hundreds of DOIs) are supported; keep concurrency modest (default 5) to avoid rate limits.
