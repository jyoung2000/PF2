"""Lexica adapter — https://lexica.art/api/v1/search?q=<term>.

Rotates through user-configured search terms (settings `lexica_search_terms`,
comma-separated), one term per run. The service is small and sometimes down:
failures land on adapter state as an error and the next run just retries (D21)."""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from .. import settings_store
from .base import ScrapedPost, SourceAdapter

API_URL = "https://lexica.art/api/v1/search"


def parse_image(img: dict) -> ScrapedPost | None:
    url = img.get("src")
    img_id = img.get("id")
    if not url or not img_id:
        return None
    width = img.get("width")
    height = img.get("height")
    params = {}
    if img.get("seed") not in (None, ""):
        params["seed"] = img["seed"]
    if width and height:
        params["size"] = f"{width}x{height}"
    prompt_id = img.get("promptid") or img.get("prompt_id")
    return ScrapedPost(
        platform="lexica",
        platform_post_id=str(img_id),
        media_url=url,
        media_type="image",
        prompt=(img.get("prompt") or None),
        model_name=img.get("model") or "Lexica Aperture",
        params=params,
        source_url=(f"https://lexica.art/prompt/{prompt_id}" if prompt_id
                    else f"https://lexica.art/?q={img_id}"),
        nsfw=bool(img.get("nsfw")),
    )


class LexicaAdapter(SourceAdapter):
    name = "lexica"
    label = "Lexica"
    tier = 1
    requires_auth = False
    capabilities = frozenset({"api", "search"})
    default_interval_minutes = 15

    def is_configured(self, s: Session) -> bool:
        return bool(self._terms(s))

    def needs_setup_reason(self, s: Session) -> str | None:
        if not self._terms(s):
            return "Add at least one search term in Settings → Scrapers"
        return None

    @staticmethod
    def _terms(s: Session) -> list[str]:
        raw = settings_store.get(s, "lexica_search_terms") or ""
        return [t.strip() for t in str(raw).split(",") if t.strip()]

    def fetch_recent(self, s: Session, client: httpx.Client,
                     limit: int = 100) -> list[ScrapedPost]:
        terms = self._terms(s)
        if not terms:
            return []
        st = self.get_state(s)
        idx = int((st.state or {}).get("term_index", 0)) % len(terms)
        term = terms[idx]
        st.state = {**(st.state or {}), "term_index": (idx + 1) % len(terms),
                    "last_term": term}
        s.flush()

        resp = client.get(API_URL, params={"q": term})
        resp.raise_for_status()
        data = resp.json()
        posts: list[ScrapedPost] = []
        for img in data.get("images") or []:
            sp = parse_image(img)
            if sp is not None:
                posts.append(sp)
                if len(posts) >= limit:
                    break
        return posts
