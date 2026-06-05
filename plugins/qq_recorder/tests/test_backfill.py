import json
import sqlite3
from pathlib import Path

from plugins.qq_recorder.backfill import (
    backfill_bot_messages,
    backfill_semantic_texts,
    ensure_backfill_columns,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_backfill_semantic_texts_recovers_image_and_video_rows(tmp_path: Path):
    db_path = tmp_path / "recorder.db"
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE image_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_unique TEXT NOT NULL,
                media_type TEXT DEFAULT 'image',
                analysis_json TEXT NOT NULL,
                semantic_text TEXT DEFAULT ''
            );
            """
        )
        conn.execute(
            """
            INSERT INTO image_analyses
                (file_unique, media_type, analysis_json,
                semantic_text)
            VALUES (?, ?, ?, '')
            """,
            (
                "img-1",
                "image",
                json.dumps(
                    {
                        "image_type": "meme",
                        "literal_content": {"summary": "图里有一段文字"},
                        "semantic_interpretation": {"main_meaning": "在吐槽加班"},
                        "confidence": 0.82,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.execute(
            """
            INSERT INTO image_analyses
                (file_unique, media_type, analysis_json,
                semantic_text)
            VALUES (?, ?, ?, '')
            """,
            (
                "video-1",
                "video",
                json.dumps(
                    {
                        "video_type": "screen_recording",
                        "duration_summary": "约 24 秒",
                        "semantic_meaning": "在说明沟通混乱",
                        "confidence": 0.91,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()

        counts = backfill_semantic_texts(conn)
        rows = conn.execute(
            "SELECT file_unique, semantic_text FROM image_analyses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert counts.scanned == 2
    assert counts.updated == 2
    assert "图片类型：meme" in rows[0]["semantic_text"]
    assert "核心含义：在吐槽加班" in rows[0]["semantic_text"]
    assert "视频类型：screen_recording" in rows[1]["semantic_text"]
    assert "核心含义：在说明沟通混乱" in rows[1]["semantic_text"]


def test_backfill_bot_messages_inserts_recoverable_trace_rows(tmp_path: Path):
    db_path = tmp_path / "recorder.db"
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id VARCHAR NOT NULL UNIQUE,
                user_id VARCHAR NOT NULL,
                group_id VARCHAR,
                chat_type VARCHAR NOT NULL,
                timestamp DATETIME NOT NULL,
                raw_message TEXT NOT NULL,
                has_image BOOLEAN DEFAULT FALSE,
                has_reply BOOLEAN DEFAULT FALSE,
                has_forward BOOLEAN DEFAULT FALSE,
                has_at BOOLEAN DEFAULT FALSE,
                has_app_share BOOLEAN DEFAULT FALSE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE message_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                segment_type VARCHAR NOT NULL,
                segment_order INTEGER NOT NULL,
                segment_data TEXT NOT NULL
            );
            CREATE TABLE replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                reply_to_message_id VARCHAR NOT NULL
            );
            CREATE TABLE agent_reply_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_message_id VARCHAR NOT NULL,
                chat_type VARCHAR NOT NULL,
                chat_id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                decision_seed VARCHAR NOT NULL,
                trigger_reason VARCHAR NOT NULL,
                response_text TEXT DEFAULT '',
                sent BOOLEAN DEFAULT 0,
                sent_message_id VARCHAR,
                sent_parts INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE reply_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_message_id VARCHAR NOT NULL,
                chat_type VARCHAR NOT NULL,
                chat_id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                decision_seed VARCHAR NOT NULL,
                decision VARCHAR NOT NULL,
                trigger_reason VARCHAR NOT NULL,
                context_ids TEXT NOT NULL DEFAULT '[]',
                prompt_variant VARCHAR NOT NULL DEFAULT 'group',
                model_response_summary TEXT DEFAULT '',
                sent BOOLEAN DEFAULT 0,
                sent_message_id VARCHAR,
                sent_parts INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        ensure_backfill_columns(conn)
        conn.execute(
            """
            INSERT INTO agent_reply_traces (
                source_message_id, chat_type, chat_id, user_id, decision_seed,
                trigger_reason, response_text, sent, sent_message_id,
                sent_parts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1, ?)
            """,
            (
                "src-agent",
                "group",
                "30001",
                "20001",
                "seed-a",
                "mention",
                "完整回复",
                "bot-agent-1",
                "2026-06-05 11:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO reply_traces (
                source_message_id, chat_type, chat_id, user_id, decision_seed,
                decision, trigger_reason, context_ids, prompt_variant,
                model_response_summary, sent, sent_message_id, sent_parts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'group', ?, 1, ?, 1, ?)
            """,
            (
                "src-reply",
                "private",
                "20002",
                "20002",
                "seed-b",
                "reply",
                "direct",
                "简短回复",
                "bot-reply-1",
                "2026-06-05 11:01:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO reply_traces (
                source_message_id, chat_type, chat_id, user_id, decision_seed,
                decision, trigger_reason, context_ids, prompt_variant,
                model_response_summary, sent, sent_message_id, sent_parts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 'group', ?, 1, ?, 1, ?)
            """,
            (
                "src-truncated",
                "group",
                "30003",
                "20003",
                "seed-c",
                "reply",
                "direct",
                "这是一段被截断的摘要…",
                "bot-reply-2",
                "2026-06-05 11:02:00",
            ),
        )
        conn.commit()

        counts = backfill_bot_messages(conn, bot_uin="10000")
        messages = conn.execute(
            """
            SELECT message_id, user_id, group_id, chat_type,
                raw_message, sender_nickname
            FROM messages ORDER BY id
            """
        ).fetchall()
        replies = conn.execute(
            "SELECT reply_to_message_id FROM replies ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert counts.scanned == 2
    assert counts.inserted == 2
    assert [row["message_id"] for row in messages] == ["bot-agent-1", "bot-reply-1"]
    assert messages[0]["user_id"] == "10000"
    assert messages[0]["group_id"] == "30001"
    assert messages[0]["chat_type"] == "group"
    assert messages[0]["raw_message"] == "完整回复"
    assert messages[0]["sender_nickname"] == "10000"
    assert messages[1]["group_id"] is None
    assert messages[1]["chat_type"] == "private"
    assert [row["reply_to_message_id"] for row in replies] == ["src-agent", "src-reply"]
