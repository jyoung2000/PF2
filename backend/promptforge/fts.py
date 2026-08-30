"""FTS5 search index, maintained explicitly from write paths (D3).

Plain FTS5 tables (rowid = row id of the source table) so single-row
delete/update works; text volume is small enough that duplication is fine.
"""
from __future__ import annotations

import re

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

POSTS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    prompt, model_name, tags, tokenize='unicode61 remove_diacritics 2'
)
"""
SAVED_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS saved_prompts_fts USING fts5(
    text, model_family, tokenize='unicode61 remove_diacritics 2'
)
"""


def ensure_fts(engine) -> None:
    with engine.begin() as conn:
        conn.execute(sql(POSTS_FTS))
        conn.execute(sql(SAVED_FTS))


def index_post(s: Session, post_id: int, prompt: str | None, model_name: str | None,
               tag_names: list[str]) -> None:
    s.execute(sql("DELETE FROM posts_fts WHERE rowid = :id"), {"id": post_id})
    s.execute(
        sql("INSERT INTO posts_fts(rowid, prompt, model_name, tags) "
            "VALUES (:id, :p, :m, :t)"),
        {"id": post_id, "p": prompt or "", "m": model_name or "",
         "t": " ".join(tag_names)},
    )


def deindex_post(s: Session, post_id: int) -> None:
    s.execute(sql("DELETE FROM posts_fts WHERE rowid = :id"), {"id": post_id})


def index_saved_prompt(s: Session, sp_id: int, text: str, model_family: str | None) -> None:
    s.execute(sql("DELETE FROM saved_prompts_fts WHERE rowid = :id"), {"id": sp_id})
    s.execute(
        sql("INSERT INTO saved_prompts_fts(rowid, text, model_family) "
            "VALUES (:id, :t, :m)"),
        {"id": sp_id, "t": text, "m": model_family or ""},
    )


def deindex_saved_prompt(s: Session, sp_id: int) -> None:
    s.execute(sql("DELETE FROM saved_prompts_fts WHERE rowid = :id"), {"id": sp_id})


_term_re = re.compile(r"[^\W_]+", re.UNICODE)


def build_match_query(free_text: str, prefix_last: bool = True) -> str | None:
    """Turn raw user text into a safe FTS5 MATCH expression: each term quoted,
    ANDed; the last term becomes a prefix query for as-you-type search."""
    terms = _term_re.findall(free_text)
    if not terms:
        return None
    quoted = [f'"{t}"' for t in terms]
    if prefix_last:
        quoted[-1] = f'"{terms[-1]}" *'.replace('" *', '"*')
    return " ".join(quoted)


def search_posts(s: Session, free_text: str, limit: int = 400) -> list[int]:
    """Ranked post ids for a free-text query (bm25)."""
    match = build_match_query(free_text)
    if match is None:
        return []
    rows = s.execute(
        sql("SELECT rowid FROM posts_fts WHERE posts_fts MATCH :q "
            "ORDER BY rank LIMIT :lim"),
        {"q": match, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]


def search_saved_prompts(s: Session, free_text: str, limit: int = 400) -> list[int]:
    match = build_match_query(free_text)
    if match is None:
        return []
    rows = s.execute(
        sql("SELECT rowid FROM saved_prompts_fts WHERE saved_prompts_fts MATCH :q "
            "ORDER BY rank LIMIT :lim"),
        {"q": match, "lim": limit},
    ).fetchall()
    return [r[0] for r in rows]
