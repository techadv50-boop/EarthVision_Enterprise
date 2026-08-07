#!/usr/bin/env python3
"""Launch WebCrawler Enterprise (source or frozen standalone)."""

from webcrawler.runtime import configure_runtime

configure_runtime()

from webcrawler.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())