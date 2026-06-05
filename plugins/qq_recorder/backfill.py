from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BackfillCounts:
    scanned: int = 0
    updated: int = 0
    inserted: int = 0
    skipped_existing: int = 0
    skipped_unrecoverable: int = 0


@dataclass(slots=True)
class TraceMessageCandidate:
    source: str
    sent_message_id: str
    source_message_id: str
    chat_type: str
    chat_id: str
    created_at: str
    text: str


def ensure_backfill_columns(conn: sqlite3.Connection) -> None:
    message_columns = _column_names(conn, "messages")
    if "messages" in _table_names(conn):
        if "sender_nickname" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN sender_nickname VARCHAR")
        if "sender_card" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN sender_card VARCHAR")
        if "has_video" not in message_columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN has_video BOOLEAN DEFAULT FALSE"
            )

    if "image_analyses" in _table_names(conn):
        analysis_columns = _column_names(conn, "image_analyses")
        if "video_id" not in analysis_columns:
            conn.execute("ALTER TABLE image_analyses ADD COLUMN video_id INTEGER")
        if "semantic_text" not in analysis_columns:
            conn.execute(
                "ALTER TABLE image_analyses ADD COLUMN semantic_text TEXT DEFAULT ''"
            )


def _try_cache_lookup(
    file_unique: str,
    cache_rows: dict[str, list[str]],
    media_type: str,
) -> str | None:
    for cached_json in cache_rows.get(file_unique, []):
        rendered = _render_semantic_text(
            cached_json,
            media_type=media_type,
        )
        if rendered:
            return rendered
    return None


def backfill_semantic_texts(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    verbose: bool = False,
) -> BackfillCounts:
    counts = BackfillCounts()
    if "image_analyses" not in _table_names(conn):
        return counts

    ensure_backfill_columns(conn)
    rows = conn.execute(
        """
        SELECT id, file_unique, media_type, analysis_json
        FROM image_analyses
        WHERE COALESCE(semantic_text, '') = ''
        ORDER BY id
        """
    ).fetchall()
    counts.scanned = len(rows)
    if not rows:
        return counts

    cache_rows = _load_vision_cache_rows(conn)
    for row in rows:
        rendered = _render_semantic_text(
            row["analysis_json"],
            media_type=str(row["media_type"] or ""),
        )
        if rendered is None:
            rendered = _try_cache_lookup(
                str(row["file_unique"] or ""),
                cache_rows,
                str(row["media_type"] or ""),
            )

        if not rendered:
            counts.skipped_unrecoverable += 1
            continue

        if verbose:
            print(f"semantic_text <- image_analyses.id={row['id']}")
        if not dry_run:
            conn.execute(
                "UPDATE image_analyses SET semantic_text = ? WHERE id = ?",
                (rendered, row["id"]),
            )
        counts.updated += 1

    if not dry_run and counts.updated:
        conn.commit()
    return counts


def backfill_bot_messages(
    conn: sqlite3.Connection,
    *,
    bot_uin: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> BackfillCounts:
    counts = BackfillCounts()
    if "messages" not in _table_names(conn):
        return counts

    ensure_backfill_columns(conn)
    existing_message_ids = {
        str(row[0])
        for row in conn.execute("SELECT message_id FROM messages").fetchall()
        if row[0]
    }

    candidates = list(_iter_trace_message_candidates(conn))
    counts.scanned = len(candidates)
    for candidate in candidates:
        if candidate.sent_message_id in existing_message_ids:
            counts.skipped_existing += 1
            continue

        if verbose:
            print(
                "bot_message <- "
                f"{candidate.source}:{candidate.sent_message_id} "
                f"reply_to={candidate.source_message_id}"
            )

        if not dry_run:
            message_db_id = _insert_bot_message(conn, candidate, bot_uin=bot_uin)
            if message_db_id is not None:
                existing_message_ids.add(candidate.sent_message_id)
        counts.inserted += 1

    if not dry_run and counts.inserted:
        conn.commit()
    return counts


def resolve_bot_uin(config_path: str) -> str:
    path = Path(config_path)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("bot_uin:"):
            continue
        _, value = line.split(":", 1)
        return value.strip().strip("'\"")
    return ""


def _iter_trace_message_candidates(
    conn: sqlite3.Connection,
) -> Iterable[TraceMessageCandidate]:
    seen: set[str] = set()

    for config in _TRACE_TABLES:
        _, source, sent_message_id_col, source_message_id_col, text_col = config
        if source not in _table_names(conn):
            continue
        rows = conn.execute(
            f"""
            SELECT {sent_message_id_col}, {source_message_id_col}, chat_type, chat_id,
                   created_at, {text_col}, sent_parts
            FROM {source}
            WHERE sent = 1
              AND {sent_message_id_col} IS NOT NULL
              AND TRIM(COALESCE({text_col}, '')) != ''
            ORDER BY created_at, id
            """
        ).fetchall()
        for row in rows:
            candidate = _try_yield_trace_candidate(
                row,
                source,
                seen,
                sent_message_id_col,
                source_message_id_col,
                text_col,
            )
            if candidate is not None:
                yield candidate


_TRACE_TABLES = [
    (
        "agent_reply_traces",
        "agent_reply_traces",
        "sent_message_id",
        "source_message_id",
        "response_text",
    ),
    (
        "reply_traces",
        "reply_traces",
        "sent_message_id",
        "source_message_id",
        "model_response_summary",
    ),
]


def _insert_bot_message(
    conn: sqlite3.Connection,
    candidate: TraceMessageCandidate,
    *,
    bot_uin: str,
) -> int | None:
    message_columns = _column_names(conn, "messages")
    raw_message = _escape_text(candidate.text)

    insert_columns: list[str] = [
        "message_id",
        "user_id",
        "group_id",
        "chat_type",
        "timestamp",
        "raw_message",
        "has_image",
        "has_reply",
        "has_forward",
        "has_at",
        "has_app_share",
    ]
    insert_values: list[Any] = [
        candidate.sent_message_id,
        bot_uin,
        candidate.chat_id if candidate.chat_type == "group" else None,
        candidate.chat_type,
        candidate.created_at,
        raw_message,
        0,
        1 if candidate.source_message_id else 0,
        0,
        0,
        0,
    ]
    if "sender_nickname" in message_columns:
        insert_columns.append("sender_nickname")
        insert_values.append(bot_uin)
    if "sender_card" in message_columns:
        insert_columns.append("sender_card")
        insert_values.append("")
    if "has_video" in message_columns:
        insert_columns.append("has_video")
        insert_values.append(0)

    placeholders = ", ".join("?" for _ in insert_columns)
    conn.execute(
        f"INSERT INTO messages ({', '.join(insert_columns)}) VALUES ({placeholders})",
        insert_values,
    )
    message_db_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        """
        INSERT INTO message_segments
            (message_id, segment_type, segment_order, segment_data)
        VALUES (?, ?, ?, ?)
        """,
        (
            message_db_id,
            "text",
            0,
            json.dumps({"text": candidate.text}, ensure_ascii=False),
        ),
    )
    if candidate.source_message_id:
        conn.execute(
            """
            INSERT INTO replies (message_id, reply_to_message_id)
            VALUES (?, ?)
            """,
            (message_db_id, candidate.source_message_id),
        )
    return message_db_id


def _render_semantic_text(
    analysis_json: str,
    *,
    media_type: str,
) -> str | None:
    try:
        payload = json.loads(analysis_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    (
        normalize_analysis,
        render_visual_context,
        normalize_video_analysis,
        render_video_context,
    ) = _import_renderers()

    detected_media_type = _detect_media_type(media_type, payload)
    if detected_media_type == "video":
        analysis = normalize_video_analysis(payload, raw_model_output=analysis_json)
        return render_video_context(analysis)

    analysis = normalize_analysis(payload, raw_model_output=analysis_json)
    return render_visual_context(analysis)


def _import_renderers():
    project_dir = str(Path(__file__).resolve().parents[2])
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    from plugins.qq_grok_reply.vision.schemas import (  # noqa: PLC0415
        normalize_analysis,
        render_visual_context,
    )
    from plugins.qq_grok_reply.vision.video_schemas import (  # noqa: PLC0415
        normalize_video_analysis,
        render_video_context,
    )

    return (
        normalize_analysis,
        render_visual_context,
        normalize_video_analysis,
        render_video_context,
    )


def _load_vision_cache_rows(conn: sqlite3.Connection) -> dict[str, list[str]]:
    if "vision_cache" not in _table_names(conn):
        return {}

    rows = conn.execute(
        """
        SELECT file_unique, analysis_json
        FROM vision_cache
        ORDER BY created_at DESC
        """
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        key = str(row["file_unique"] or "").strip()
        value = str(row["analysis_json"] or "")
        if not key or not value:
            continue
        grouped.setdefault(key, []).append(value)
    return grouped


def _detect_media_type(media_type: str, payload: dict[str, Any]) -> str:
    normalized = media_type.strip().lower()
    if normalized in {"image", "video"}:
        return normalized
    if str(payload.get("media_type", "") or "").strip().lower() == "video":
        return "video"
    if "video_type" in payload or "duration_summary" in payload:
        return "video"
    return "image"


def _looks_like_full_reply_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith("…") or stripped.endswith("..."):
        return False
    return "[request_more_context]" not in stripped


def _is_multi_part_reply(sent_parts: Any) -> bool:
    try:
        return int(sent_parts or 0) > 1
    except (TypeError, ValueError):
        return False


def _normalize_chat_type(chat_type: str) -> str:
    return "group" if chat_type == "group" else "private"


def _try_yield_trace_candidate(
    row: sqlite3.Row,
    source: str,
    seen: set[str],
    sent_message_id_col: str,
    source_message_id_col: str,
    text_col: str,
) -> TraceMessageCandidate | None:
    sent_message_id = str(row[sent_message_id_col] or "").strip()
    text = str(row[text_col] or "")
    if not sent_message_id or not text.strip():
        return None
    if _is_multi_part_reply(row["sent_parts"]):
        return None
    if source == "reply_traces" and not _looks_like_full_reply_text(text):
        return None
    if sent_message_id in seen:
        return None
    seen.add(sent_message_id)
    return TraceMessageCandidate(
        source=source,
        sent_message_id=sent_message_id,
        source_message_id=str(row[source_message_id_col] or "").strip(),
        chat_type=_normalize_chat_type(str(row["chat_type"] or "")),
        chat_id=str(row["chat_id"] or "").strip(),
        created_at=str(row["created_at"] or ""),
        text=text,
    )


def _escape_text(text: str) -> str:
    if not text:
        return text
    return (
        text.replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if table_name not in _table_names(conn):
        return set()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}
