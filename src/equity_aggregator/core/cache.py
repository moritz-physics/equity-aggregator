"""Local SQLite-backed cache for adapter responses.

Keyed by index name (e.g. ``"DAX"``); stores the full Index model as JSON.
Entries expire after ``ttl_seconds`` — reads past TTL return ``None`` and
the service layer re-fetches.

Mirrors the bond-aggregator cache pattern: one table, one row per index,
upsert-on-write (delete + insert).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select

from equity_aggregator.core.models import Index

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "cache.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)


class CachedIndex(SQLModel, table=True):
    """One row per cached Index snapshot. ``payload`` is JSON-serialised Index."""

    id: int | None = Field(default=None, primary_key=True)
    index_name: str = Field(index=True)
    country: str
    payload: str
    fetched_at: datetime
    ttl_seconds: int = Field(default=DEFAULT_TTL_SECONDS)


def _make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    SQLModel.metadata.create_all(engine)
    return engine


_default_engine: Engine = _make_engine(DB_PATH)


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on read — re-attach UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class ConstituentCache:
    """SQLite-backed Index cache with per-entry TTL.

    ``db_path=None`` (default) uses the project-wide ``data/cache.db``.
    Pass an explicit path (e.g. ``tmp_path / "cache.db"`` in tests) to use
    an isolated DB.
    """

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        default_ttl_seconds: int = DEFAULT_TTL_SECONDS,
        ttl_seconds: int | None = None,
    ) -> None:
        self._engine: Engine = (
            _default_engine if db_path is None else _make_engine(db_path)
        )
        self._default_ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else default_ttl_seconds
        )

    def _now(self) -> datetime:
        return datetime.now(tz=UTC)

    def _is_expired(self, row: CachedIndex) -> bool:
        return self._now() >= _aware(row.fetched_at) + timedelta(
            seconds=row.ttl_seconds
        )

    def _rows_for(self, session: Session, index_name: str) -> list[CachedIndex]:
        stmt = select(CachedIndex).where(
            cast(Any, CachedIndex.index_name) == index_name
        )
        return list(session.exec(stmt).all())

    def get(self, index_name: str) -> Index | None:
        with Session(self._engine) as session:
            rows = self._rows_for(session, index_name)
            if not rows:
                return None
            row = rows[0]
            if self._is_expired(row):
                return None
            try:
                return Index.model_validate_json(row.payload)
            except Exception as exc:
                logger.warning("Cache payload for %s unreadable: %s", index_name, exc)
                return None

    def set(self, index: Index) -> None:
        payload = index.model_dump_json()
        with Session(self._engine) as session:
            for row in self._rows_for(session, index.name):
                session.delete(row)
            session.add(
                CachedIndex(
                    index_name=index.name,
                    country=index.country,
                    payload=payload,
                    fetched_at=self._now(),
                    ttl_seconds=self._default_ttl_seconds,
                )
            )
            session.commit()

    def invalidate(self, index_name: str) -> None:
        with Session(self._engine) as session:
            for row in self._rows_for(session, index_name):
                session.delete(row)
            session.commit()

    def invalidate_all(self) -> None:
        with Session(self._engine) as session:
            for row in session.exec(select(CachedIndex)).all():
                session.delete(row)
            session.commit()

    def stats(self) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        with Session(self._engine) as session:
            rows = list(session.exec(select(CachedIndex)).all())
        for row in rows:
            fetched_at = _aware(row.fetched_at)
            out[row.index_name] = {
                "fetched_at": fetched_at,
                "expires_at": fetched_at + timedelta(seconds=row.ttl_seconds),
                "ttl_seconds": row.ttl_seconds,
                "hit": not self._is_expired(row),
            }
        return out
