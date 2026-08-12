# DOI / URL → ReDIF Converter

Turn a list of **DOIs and/or article page URLs** into one **ReDIF-Article 1.0** file each (IJIST / RePEc style, e.g. `V8i3p1429-1448.redif`).

## Easiest: download and run (standalone desktop)

Download from GitHub Releases:

| System | File |
|--------|------|
| Windows | `DOI_REDIF_Converter-windows.zip` → run `Run_DOI_REDIF_Converter.bat` |
| macOS | `DOI_REDIF_Converter-macos.zip` → run `DOI_REDIF_Converter` |
| Linux | `DOI_REDIF_Converter-linux.zip` → run `DOI_REDIF_Converter` |

1. Unzip
2. Double-click the program
3. A **desktop window** opens (no browser)
4. Paste DOIs / article URLs or load Excel → **Start conversion** → **Export ZIP**

Internet is required (to open each DOI/URL / Crossref).

### Build the standalone program yourself

```bash
cd doi-redif-converter
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements-build.txt
python build_app.py
```

The executable appears in `dist/`.

## Easy (with Python installed): double-click starter

### Windows
Double-click:

`Start_DOI_REDIF_Converter.bat`

Or in PowerShell from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python DOI_REDIF_Converter.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python DOI_REDIF_Converter.py
```

## Developer server (optional)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Open http://127.0.0.1:8001

## CLI batch mode

```bash
python -m app.cli -i samples/DOI_Record.xlsx -o redif_out
```

## What it extracts

Authors, affiliations, title, abstract, keywords, journal, volume, issue, pages, year, month, DOI, file URLs, and RePEc handle (`RePEc:abq:IJIST1:...` by default).

Author emails are included only when publicly available on the article page or Crossref.

## Failures and final report

- Inaccessible / 404 DOIs are skipped automatically; processing continues to the end of the list
- Live progress shows done / left while running
- Final report shows total, succeeded, failed, and the exact DOIs that could not be converted
- ZIP export always includes `_conversion_report.txt` and `_failed.csv`
