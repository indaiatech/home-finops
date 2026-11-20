"""FinOps sync worker: loads YAML IaC configs and periodically pulls Pluggy data."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from finops.config.loader import load_and_sync_config
from finops.db.session import SessionLocal
from finops.ingestion.demo_seed import seed_demo_data
from finops.ingestion.pluggy_adapter import PluggyApiAdapter
from finops.settings import ROOT_DIR, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("finops.worker")


def _config_dir(override: Path | None) -> Path:
    if override is not None:
        return override
    cfg = get_settings().resolved_config_dir()
    if cfg.exists() and (cfg / "people.yaml").exists():
        return cfg
    return ROOT_DIR / "config" / "examples"


def run_sync_cycle(config_dir: Path, seed_demo: bool = False) -> None:
    db = SessionLocal()
    try:
        logger.info("Syncing declarative YAML configs from %s", config_dir)
        bundle = load_and_sync_config(db, config_dir)

        if seed_demo:
            seeded = seed_demo_data(db, bundle)
            logger.info("Demo seed completed: %s", seeded)
            return

        adapter = PluggyApiAdapter()
        results = adapter.sync_all(db, bundle)
        for res in results:
            logger.info("Pluggy sync result: %s", res)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="FinOps Sync Worker")
    parser.add_argument("--once", action="store_true", help="Run one sync cycle and exit.")
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Populate synthetic 2-person demo data instead of calling live Pluggy APIs.",
    )
    parser.add_argument("--config-dir", type=Path, default=None)
    args = parser.parse_args()

    cfg_dir = _config_dir(args.config_dir)
    if args.once or args.seed_demo:
        run_sync_cycle(cfg_dir, seed_demo=args.seed_demo)
        return 0

    interval_seconds = max(60, get_settings().finops_sync_interval_minutes * 60)
    logger.info("Starting FinOps sync daemon (interval=%ss)", interval_seconds)
    while True:
        try:
            run_sync_cycle(cfg_dir)
        except Exception:
            logger.exception("Unhandled error during sync cycle")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
