"""Traffic forecasting and ML model registry REST API router.

Provides endpoints for triggering model training, executing 30-minute forward predictions,
and inspecting registered forecasting model versions and evaluation metrics.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai.forecasting.pipeline import load_latest_forecaster
from ai.forecasting.registry import ModelRegistry
from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.ml import MLModel
from app.realtime import emit_prediction_published
from app.schemas.forecasting import (
    ModelVersionInfo,
    PredictBatchResponse,
    PredictRequest,
    TrainRequest,
)
from app.services.forecasting import (
    ForecastingInsufficientDataError,
    ForecastingModelNotFoundError,
    predict_and_store,
    train_and_register,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/forecasting",
    tags=["forecasting"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/train",
    status_code=status.HTTP_200_OK,
    summary="Train and register traffic forecasting model (admin only)",
)
async def train_model(
    payload: TrainRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Train a multi-target traffic forecasting model on historical telemetry and register it.

    Execution note:
        Training runs synchronously and blocks until model fitting, out-of-sample evaluation,
        and artifact persistence complete (~2-5 seconds depending on telemetry dataset volume).

    Raises:
        HTTP 422: If historical telemetry rows are below pipeline threshold (minimum ~2000 records).
    """
    try:
        report = await train_and_register(
            db=db,
            intersection_ids=payload.intersection_ids,
            days=payload.days,
            notes=payload.notes,
        )
    except ForecastingInsufficientDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "insufficient_data",
                "rows_found": exc.rows_found,
                "rows_required": exc.rows_required,
                "message": exc.message,
            },
        )

    # Sanitize report for JSON serialization (strip model instance)
    clean_report = {k: v for k, v in report.items() if k != "model"}

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="forecasting.model_trained",
        actor_user_id=current_user.id,
        entity_type="ml_model",
        entity_id=clean_report.get("id"),
        details={
            "version": clean_report.get("version"),
            "days": payload.days,
            "n_train_rows": clean_report.get("n_train_rows"),
            "notes": payload.notes,
        },
        ip_address=client_ip,
    )

    return clean_report


@router.post(
    "/predict",
    response_model=PredictBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate 30-minute forward predictions (officer or admin)",
)
async def generate_predictions(
    payload: PredictRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> dict[str, Any]:
    """Generate multi-target traffic forecasts for target intersections and record in AIPrediction.

    Evaluates recent 24-hour telemetry window. Intersections with fewer than 20 records
    are marked with status 'insufficient_data' containing row counts, guaranteeing no fabricated
    forecasts are produced.
    """
    try:
        results = await predict_and_store(
            db=db,
            intersection_ids=payload.intersection_ids,
        )
    except ForecastingModelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    predictions = [r for r in results if r.get("status") == "predicted"]
    insufficient = [r for r in results if r.get("status") == "insufficient_data"]

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="forecasting.predictions_generated",
        actor_user_id=current_user.id,
        entity_type="ai_prediction",
        entity_id=None,
        details={
            "intersection_ids": payload.intersection_ids,
            "predicted_count": len(predictions),
            "insufficient_count": len(insufficient),
        },
        ip_address=client_ip,
    )

    if predictions:
        model_ver = predictions[0].get("model_version", "unknown")
        pred_junction_ids = [r["intersection_id"] for r in predictions]
        await emit_prediction_published(
            model_version=model_ver,
            horizon_minutes=30,
            junction_ids=pred_junction_ids,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    return {
        "predictions": predictions,
        "insufficient": insufficient,
    }


@router.get(
    "/models",
    response_model=list[ModelVersionInfo],
    status_code=status.HTTP_200_OK,
    summary="List registered forecasting model versions with DB cross-check",
)
async def list_models(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all registered forecasting models across filesystem artifacts and database records."""
    # 1. Fetch database records
    stmt = select(MLModel).order_by(MLModel.created_at.asc())
    res = await db.execute(stmt)
    db_models = {m.version: m for m in res.scalars().all()}

    # 2. Fetch disk registry versions
    reg = ModelRegistry()
    disk_versions = reg.list_versions()
    disk_version_names = {v.get("version") for v in disk_versions if v.get("version")}

    combined: list[dict[str, Any]] = []

    # Process disk versions first
    for d_meta in disk_versions:
        ver_str = d_meta.get("version", "")
        db_match = db_models.get(ver_str)

        combined.append({
            "id": db_match.id if db_match else None,
            "name": db_match.name if db_match else "traffic_forecaster",
            "version": ver_str,
            "artifact_path": db_match.artifact_path if db_match else str(reg.root / ver_str),
            "metrics": d_meta.get("metrics") or (db_match.metrics if db_match else {}),
            "data_summary": d_meta.get("data_summary") or (db_match.data_summary if db_match else None),
            "feature_names": d_meta.get("feature_names") or (db_match.feature_names if db_match else None),
            "horizon_steps": (
                d_meta.get("horizon", {}).get("steps")
                or (db_match.horizon_steps if db_match else 6)
            ),
            "notes": d_meta.get("notes") or (db_match.notes if db_match else None),
            "created_at": db_match.created_at if db_match else None,
            "in_database": db_match is not None,
            "in_filesystem": True,
        })

    # Add any database models not on disk
    for ver_str, db_model in db_models.items():
        if ver_str not in disk_version_names:
            combined.append({
                "id": db_model.id,
                "name": db_model.name,
                "version": db_model.version,
                "artifact_path": db_model.artifact_path,
                "metrics": db_model.metrics,
                "data_summary": db_model.data_summary,
                "feature_names": db_model.feature_names,
                "horizon_steps": db_model.horizon_steps,
                "notes": db_model.notes,
                "created_at": db_model.created_at,
                "in_database": True,
                "in_filesystem": False,
            })

    return combined


@router.get(
    "/models/latest",
    response_model=ModelVersionInfo,
    status_code=status.HTTP_200_OK,
    summary="Get latest forecasting model metadata and evaluation metrics",
)
async def get_latest_model(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve metadata, parameters, and out-of-sample metrics for the latest registered forecaster."""
    reg = ModelRegistry()
    try:
        _, metadata = reg.get_latest()
    except FileNotFoundError:
        # Check if database has any record
        stmt = select(MLModel).order_by(MLModel.id.desc()).limit(1)
        res = await db.execute(stmt)
        latest_db = res.scalar_one_or_none()
        if not latest_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No forecasting models registered in system.",
            )
        return {
            "id": latest_db.id,
            "name": latest_db.name,
            "version": latest_db.version,
            "artifact_path": latest_db.artifact_path,
            "metrics": latest_db.metrics,
            "data_summary": latest_db.data_summary,
            "feature_names": latest_db.feature_names,
            "horizon_steps": latest_db.horizon_steps,
            "notes": latest_db.notes,
            "created_at": latest_db.created_at,
            "in_database": True,
            "in_filesystem": False,
        }

    latest_ver = metadata.get("version", "")
    stmt = select(MLModel).where(MLModel.version == latest_ver).limit(1)
    res = await db.execute(stmt)
    db_match = res.scalar_one_or_none()

    return {
        "id": db_match.id if db_match else None,
        "name": db_match.name if db_match else "traffic_forecaster",
        "version": latest_ver,
        "artifact_path": db_match.artifact_path if db_match else str(reg.root / latest_ver),
        "metrics": metadata.get("metrics", {}),
        "data_summary": metadata.get("data_summary"),
        "feature_names": metadata.get("feature_names"),
        "horizon_steps": metadata.get("horizon", {}).get("steps", 6),
        "notes": metadata.get("notes") or (db_match.notes if db_match else None),
        "created_at": db_match.created_at if db_match else None,
        "in_database": db_match is not None,
        "in_filesystem": True,
    }
