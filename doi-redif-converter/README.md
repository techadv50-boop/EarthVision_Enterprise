# DOI → ReDIF Converter

Turn a list of DOIs into one **ReDIF-Article 1.0** file per DOI (IJIST / RePEc style, e.g. `V8i3p1429-1448.redif`).

## Easiest: download and run (no Python)

After CI builds finish, download the zip for your OS from the GitHub Actions artifacts or a Release:

| System | File |
|--------|------|
| Windows | `DOI_REDIF_Converter-windows.zip` → run `DOI_REDIF_Converter.exe` |
| macOS | `DOI_REDIF_Converter-macos.zip` → run `DOI_REDIF_Converter` |
| Linux | `DOI_REDIF_Converter-linux.zip` → run `DOI_REDIF_Converter` |

1. Unzip
2. Double-click the program
3. Your browser opens the app UI
4. Keep the small control window open while using it
5. Paste DOIs or upload Excel → **Extract & preview** → **Download ZIP**

Internet is required (to open each DOI / Crossref).

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
