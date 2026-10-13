#!/usr/bin/env python3
"""Training entrypoint for PyTorch LSTM traffic flow forecasting model.

Loads historical traffic telemetry from the database using load_training_frame.
If the database has insufficient rows, deterministically generates a synthetic
training set (fixed random seed, documented) and explicitly labels the artifact
provenance as 'synthetic-deterministic-seed-N'.

The resulting artifact is persisted through ModelRegistry and registered in
the ml_models PostgreSQL table.

Usage:
    cd backend && .venv/bin/python scripts/train_flow_lstm.py [--days 21] [--epochs 5] [--seed 42] [--force-synthetic]
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

# Ensure backend root and workspace root are in sys.path
backend_dir = Path(__file__).resolve().parent.parent
workspace_dir = backend_dir.parent
for p in [str(backend_dir), str(workspace_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app.core.database import AsyncSessionLocal, engine
from app.services.flow_lstm import train_and_register_flow_lstm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_flow_lstm")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train and register PyTorch Flow LSTM forecasting model.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=21,
        help="Lookback duration in days for querying database records (default: 21).",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
        help="Training epochs for PyTorch LSTM on CPU (default: 5).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic random seed for generation and initialization (default: 42).",
    )
    parser.add_argument(
        "--force-synthetic",
        action="store_true",
        help="Force generation of deterministic synthetic telemetry even if database has rows.",
    )
    parser.add_argument(
        "--intersections",
        type=int,
        nargs="*",
        default=None,
        help="Optional list of intersection IDs to filter or simulate.",
    )
    parser.add_argument(
        "--registry-root",
        type=str,
        default=None,
        help="Optional custom root directory for model artifacts.",
    )

    args = parser.parse_args()

    logger.info("Initializing LSTM flow model training job...")
    logger.info(
        "Parameters: days=%d, epochs=%d, seed=%d, force_synthetic=%s, intersections=%s",
        args.days,
        args.epochs,
        args.seed,
        args.force_synthetic,
        args.intersections,
    )

    async with AsyncSessionLocal() as session:
        try:
            report = await train_and_register_flow_lstm(
                db=session,
                intersection_ids=args.intersections,
                days=args.days,
                notes=f"Trained via train_flow_lstm.py (epochs={args.epochs}, seed={args.seed})",
                epochs=args.epochs,
                force_synthetic=args.force_synthetic,
                seed=args.seed,
                registry_root=args.registry_root,
            )
        except Exception as exc:
            logger.error("Training job failed: %s", exc, exc_info=True)
            return 1

    await engine.dispose()

    print("\n" + "=" * 60)
    print("LSTM Flow Model Training & Registration Complete")
    print("=" * 60)
    print(f"Model Name:        {report['name']}")
    print(f"Assigned Version:  {report['version']}")
    print(f"Database ID:       {report['id']}")
    print(f"Architecture:      {report['architecture']}")
    print(f"Provenance:        {report['training_data_provenance']}")
    print(f"Training Rows:     {report['training_rows']}")
    print(f"Artifact Location: {report['artifact_path']}")
    print(f"Trained At:        {report['trained_at']}")
    print(f"Metrics:           {json.dumps(report['metrics'], indent=2)}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
