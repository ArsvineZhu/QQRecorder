"""SQLite-backed cache for image and video analysis results."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import Column, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .schemas import VisualAnalysis, analysis_to_dict, normalize_analysis
from .video_schemas import (
    VideoAnalysis,
    normalize_video_analysis,
    video_analysis_to_dict,
)

logger = logging.getLogger("qq_grok_reply.vision.cache")

Base = declarative_base()
AnalysisT = TypeVar("AnalysisT", VisualAnalysis, VideoAnalysis)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class VisionCacheRow(Base):
    __tablename__ = "vision_cache"

    file_unique: str = Column(String, primary_key=True)  # type: ignore[assignment]
    model_used: str = Column(String, primary_key=True)  # type: ignore[assignment]
    prompt_version: str = Column(String, primary_key=True)  # type: ignore[assignment]
    analysis_json: str = Column(Text, nullable=False)  # type: ignore[assignment]
    image_type: str = Column(String, default="")  # type: ignore[assignment]
    confidence: float = Column(Float, default=0.0)  # type: ignore[assignment]
    created_at: datetime = Column(DateTime, default=_utcnow_naive)  # type: ignore[assignment]


class VisionCacheStore:
    """Cache keyed by ``(file_unique, model_used, prompt_version)``."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.engine = None
        self._Session = None

    async def init_db(self) -> None:
        engine_path = self._engine_path()
        self.engine = create_engine(engine_path, echo=False)
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)
        logger.info("vision: cache initialized db=%s", self.db_path)

    async def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self._Session = None

    async def get_visual(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        *,
        ttl_days: int | None = None,
    ) -> VisualAnalysis | None:
        return await self._get(
            file_unique,
            model_used,
            prompt_version,
            ttl_days=ttl_days,
            parser=lambda payload: normalize_analysis(
                payload, raw_model_output=json.dumps(payload, ensure_ascii=False)
            ),
        )

    async def get_video(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        *,
        ttl_days: int | None = None,
    ) -> VideoAnalysis | None:
        return await self._get(
            file_unique,
            model_used,
            prompt_version,
            ttl_days=ttl_days,
            parser=lambda payload: normalize_video_analysis(
                payload, raw_model_output=json.dumps(payload, ensure_ascii=False)
            ),
        )

    async def put_visual(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        analysis: VisualAnalysis,
    ) -> None:
        await self._put(
            file_unique,
            model_used,
            prompt_version,
            analysis_json=json.dumps(analysis_to_dict(analysis), ensure_ascii=False),
            content_type=analysis.image_type,
            confidence=analysis.confidence,
        )

    async def put_video(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        analysis: VideoAnalysis,
    ) -> None:
        await self._put(
            file_unique,
            model_used,
            prompt_version,
            analysis_json=json.dumps(
                video_analysis_to_dict(analysis), ensure_ascii=False
            ),
            content_type=analysis.video_type,
            confidence=analysis.confidence,
        )

    async def _get(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        *,
        ttl_days: int | None,
        parser: Callable[[dict[str, Any]], AnalysisT],
    ) -> AnalysisT | None:
        session_factory = self._Session
        if session_factory is None:
            return None

        expires_before = _expiry_cutoff(ttl_days)

        def _query() -> VisionCacheRow | None:
            with session_factory() as session:  # type: ignore[operator]
                row = (
                    session.query(VisionCacheRow)
                    .filter_by(
                        file_unique=file_unique,
                        model_used=model_used,
                        prompt_version=prompt_version,
                    )
                    .first()
                )
                if row is None:
                    return None
                if (
                    expires_before is not None
                    and _coerce_utc(row.created_at) < expires_before
                ):
                    return None
                return row

        row = await asyncio.to_thread(_query)
        if row is None:
            return None

        try:
            payload = json.loads(row.analysis_json)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning(
                "vision: cache corrupted file_unique=%s model=%s error=%s",
                file_unique,
                model_used,
                exc,
            )
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "vision: cache payload is not an object file_unique=%s model=%s",
                file_unique,
                model_used,
            )
            return None
        return parser(payload)

    async def _put(
        self,
        file_unique: str,
        model_used: str,
        prompt_version: str,
        *,
        analysis_json: str,
        content_type: str,
        confidence: float,
    ) -> None:
        session_factory = self._Session
        if session_factory is None:
            return

        def _upsert() -> None:
            with session_factory() as session:  # type: ignore[operator]
                row = (
                    session.query(VisionCacheRow)
                    .filter_by(
                        file_unique=file_unique,
                        model_used=model_used,
                        prompt_version=prompt_version,
                    )
                    .first()
                )
                if row is None:
                    session.add(
                        VisionCacheRow(
                            file_unique=file_unique,
                            model_used=model_used,
                            prompt_version=prompt_version,
                            analysis_json=analysis_json,
                            image_type=content_type,
                            confidence=confidence,
                        )
                    )
                else:
                    row.analysis_json = analysis_json
                    row.image_type = content_type
                    row.confidence = confidence
                    row.created_at = _utcnow_naive()
                session.commit()

        await asyncio.to_thread(_upsert)

    def _engine_path(self) -> str:
        if self.db_path == ":memory:":
            return "sqlite:///:memory:"
        if "://" in self.db_path:
            return self.db_path
        return f"sqlite:///{Path(self.db_path).resolve().as_posix()}"


def _expiry_cutoff(ttl_days: int | None) -> datetime | None:
    if ttl_days is None or ttl_days <= 0:
        return None
    return datetime.now(UTC) - timedelta(days=ttl_days)


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
