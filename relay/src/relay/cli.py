"""Command line entry for the file relay."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable

from relay.config import Endpoint, Settings, load_settings
from relay.connectors import connect
from relay.service import RelayService
from relay.store import Store

ConnectorFactory = Callable[[Endpoint], object]


def main(argv: list[str] | None = None, connector_factory: ConnectorFactory | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll shared-hosting and VPS drop folders over SFTP and forward "
            "new or changed files. Local copies are deleted after their configured life."
        )
    )
    parser.add_argument("--config", required=True, help="path to config.yaml")
    parser.add_argument(
        "--once",
        action="store_true",
        help="poll every source one time, sweep expired local copies, then exit",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = load_settings(args.config)
    store = Store(settings.database_path)
    try:
        store.migrate()
        service = RelayService(
            settings,
            store,
            connector_factory or connect,
        )
        if args.once:
            service.run_once()
        else:
            service.run_forever()
    finally:
        store.close()
    return 0


def build_service(settings: Settings, connector_factory: ConnectorFactory | None = None) -> RelayService:
    store = Store(settings.database_path)
    store.migrate()
    return RelayService(settings, store, connector_factory or connect)
