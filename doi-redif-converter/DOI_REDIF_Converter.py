"""Entry point used by older scripts — redirects to native standalone GUI."""

from __future__ import annotations

from DOI_REDIF_Standalone import main

if __name__ == "__main__":
    raise SystemExit(main())
