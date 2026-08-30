"""X.com (Twitter) adapter (Phase X1, D51/D55) — browser-based with the
user's paid login session; intercepts X's internal GraphQL timeline JSON
(SearchTimeline / UserTweets / UserMedia), never the rendered DOM. Freeform
prompt/model mining happens in x_text.py (deterministic). One Post per media
item; a multi-image tweet becomes `{tweet_id}`, `{tweet_id}-1`, …

Logged-in scraping runs against the user's own account and X's ToS — polling
stays gentle (VirtualScroll, one browser at a time, conservative backoff)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from .. import settings_store
from .base import ScrapedPost
from .browser_base import BrowserAdapter, walk_find_lists
from . import x_text

GRAPHQL_OPS = ("searchtimeline", "usertweets", "usermedia", "tweetdetail",
               "hometimeline", "homelatesttimeline", "bookmarks")


def _parse_created_at(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None


def _unwrap(result: dict) -> dict:
    """GraphQL sometimes wraps: result.tweet.result / TweetWithVisibilityResults."""
    inner = result.get("tweet")
    if isinstance(inner, dict):
        return inner.get("result", inner) if "result" in inner else inner
    return result


def _tweet_predicate(node: dict) -> bool:
    legacy = node.get("legacy")
    return (isinstance(node.get("rest_id"), str)
            and isinstance(legacy, dict)
            and isinstance(legacy.get("full_text"), str))


def _author(result: dict) -> tuple[str | None, str | None]:
    user = (((result.get("core") or {}).get("user_results") or {})
            .get("result") or {})
    for container in (user.get("legacy") or {}, user.get("core") or {}):
        handle = container.get("screen_name")
        if handle:
            return handle, container.get("name")
    return None, None


def _full_text(result: dict, legacy: dict) -> str:
    note = (((result.get("note_tweet") or {}).get("note_tweet_results") or {})
            .get("result") or {})
    if isinstance(note.get("text"), str) and len(note["text"]) > len(
            legacy.get("full_text", "")):
        return note["text"]
    return legacy.get("full_text", "")


def _quoted_text(result: dict) -> str | None:
    quoted = _unwrap(((result.get("quoted_status_result") or {})
                      .get("result")) or {})
    q_legacy = quoted.get("legacy") if isinstance(quoted, dict) else None
    if isinstance(q_legacy, dict):
        return q_legacy.get("full_text")
    return None


def _best_media_url(media: dict) -> tuple[str | None, str]:
    """→ (url, media_type). Photos at original quality; videos at top bitrate."""
    mtype = media.get("type")
    if mtype == "photo":
        url = media.get("media_url_https")
        if not url:
            return None, "image"
        return (url if "?" in url else f"{url}?name=orig"), "image"
    if mtype in ("video", "animated_gif"):
        variants = ((media.get("video_info") or {}).get("variants") or [])
        mp4s = [v for v in variants
                if v.get("content_type") == "video/mp4" and v.get("url")]
        if not mp4s:
            return None, "video"
        best = max(mp4s, key=lambda v: v.get("bitrate") or 0)
        return best["url"], "video"
    return None, "image"


def parse_tweet(result: dict) -> list[ScrapedPost]:
    """One GraphQL tweet result → 0..n ScrapedPosts (one per media item)."""
    result = _unwrap(result)
    legacy = result.get("legacy") or {}
    # retweets: index the original, not the RT wrapper
    rt = ((legacy.get("retweeted_status_result") or {}).get("result"))
    if isinstance(rt, dict):
        return parse_tweet(rt)
    tweet_id = result.get("rest_id")
    if not tweet_id:
        return []
    media_list = ((legacy.get("extended_entities") or {}).get("media")
                  or (legacy.get("entities") or {}).get("media") or [])
    if not media_list:
        return []

    handle, display_name = _author(result)
    text = _full_text(result, legacy)
    quoted = _quoted_text(result)
    extracted = x_text.extract(text, quoted)

    engagement = {
        "likes": legacy.get("favorite_count") or 0,
        "reposts": legacy.get("retweet_count") or 0,
        "replies": legacy.get("reply_count") or 0,
        "quotes": legacy.get("quote_count") or 0,
    }
    posted_at = _parse_created_at(legacy.get("created_at"))
    is_reply = bool(legacy.get("in_reply_to_status_id_str"))
    nsfw = bool(legacy.get("possibly_sensitive"))
    source_url = (f"https://x.com/{handle}/status/{tweet_id}" if handle
                  else f"https://x.com/i/status/{tweet_id}")

    posts: list[ScrapedPost] = []
    for i, media in enumerate(media_list):
        url, media_type = _best_media_url(media)
        if not url:
            continue
        params: dict[str, Any] = {
            "engagement": engagement,
            "prompt_confidence": extracted.prompt_confidence,
            "model_stated": extracted.model_stated,
            "_is_reply": is_reply,
        }
        if extracted.hashtags:
            params["hashtags"] = extracted.hashtags[:12]
        if i > 0:
            params["media_index"] = i
        info = media.get("original_info") or {}
        if info.get("width") and info.get("height"):
            params["size"] = f"{info['width']}x{info['height']}"
        posts.append(ScrapedPost(
            platform="x",
            platform_post_id=str(tweet_id) if i == 0 else f"{tweet_id}-{i}",
            media_url=url,
            media_type=media_type,
            prompt=extracted.prompt,
            negative_prompt=extracted.negative,
            model_name=extracted.model_name,
            params=params,
            author=f"@{handle}" if handle else display_name,
            source_url=source_url,
            posted_at=posted_at,
            nsfw=nsfw,
        ))
    return posts


def _parse_adaptive(payload: dict) -> list[dict]:
    """Legacy adaptive.json shape → pseudo GraphQL results."""
    tweets = ((payload.get("globalObjects") or {}).get("tweets") or {})
    users = ((payload.get("globalObjects") or {}).get("users") or {})
    out = []
    for tid, t in tweets.items():
        user = users.get(str(t.get("user_id_str") or t.get("user_id"))) or {}
        out.append({
            "rest_id": str(tid),
            "legacy": t,
            "core": {"user_results": {"result": {"legacy": {
                "screen_name": user.get("screen_name"),
                "name": user.get("name")}}}},
        })
    return out


class XAdapter(BrowserAdapter):
    name = "x"
    label = "X (Twitter)"
    requires_auth = True
    default_interval_minutes = 45
    min_interval_minutes = 15
    start_url = "https://x.com/explore"
    scroll_mode = "virtual"
    virtual_scroll_selector = '[data-testid="primaryColumn"]'
    scroll_count = 8

    def wants_response(self, url: str) -> bool:
        u = url.lower()
        if "adaptive.json" in u:
            return True
        return "/i/api/graphql/" in u and any(op in u for op in GRAPHQL_OPS)

    # -- parsing -------------------------------------------------------------
    def parse_captured(self, responses: list[dict]) -> list[ScrapedPost]:
        posts: list[ScrapedPost] = []
        seen: set[str] = set()
        for resp in responses:
            payload = resp.get("json")
            results = walk_find_lists(payload, _tweet_predicate, max_depth=20)
            if not results and isinstance(payload, dict) and \
                    "globalObjects" in payload:
                results = _parse_adaptive(payload)
            for result in results:
                for sp in parse_tweet(result):
                    if sp.platform_post_id not in seen:
                        seen.add(sp.platform_post_id)
                        posts.append(sp)
        posts.sort(key=lambda p: self._tweet_num(p), reverse=True)  # newest first
        return posts

    @staticmethod
    def _tweet_num(sp: ScrapedPost) -> int:
        try:
            return int(str(sp.platform_post_id).split("-")[0])
        except ValueError:
            return 0

    # -- scope filters (X1.4) -------------------------------------------------
    def apply_scope(self, s: Session, posts: list[ScrapedPost],
                    limit: int | None = None) -> list[ScrapedPost]:
        min_engagement = int(settings_store.get(s, "x_min_engagement") or 0)
        media_filter = settings_store.get(s, "x_media_filter") or "both"
        skip_replies = bool(settings_store.get(s, "x_skip_replies"))
        max_per_run = int(settings_store.get(s, "x_max_per_run") or 40)
        out = []
        for sp in posts:
            eng = (sp.params or {}).get("engagement") or {}
            if (eng.get("likes", 0) + eng.get("reposts", 0)) < min_engagement:
                continue
            if media_filter == "images" and sp.media_type != "image":
                continue
            if media_filter == "videos" and sp.media_type != "video":
                continue
            if skip_replies and (sp.params or {}).get("_is_reply"):
                continue
            out.append(sp)
        return out[: (limit if limit is not None else max_per_run)]

    # -- crawls ---------------------------------------------------------------
    def _terms(self, s: Session) -> list[str]:
        raw = settings_store.get(s, "x_search_terms") or ""
        return [t.strip() for t in str(raw).split(",") if t.strip()]

    def fetch_recent(self, s: Session, client, limit: int = 100) -> list[ScrapedPost]:
        terms = self._terms(s)
        if terms:
            st = self.get_state(s)
            idx = int((st.state or {}).get("term_index", 0)) % len(terms)
            term = terms[idx]
            st.state = {**(st.state or {}), "term_index": (idx + 1) % len(terms),
                        "last_term": term}
            s.flush()
            self.start_url = ("https://x.com/search?q=" + quote(term)
                              + "&src=typed_query&f=live")
        else:
            self.start_url = "https://x.com/explore"
        posts = super().fetch_recent(s, client, limit=10_000)
        return self.apply_scope(s, posts, limit=min(
            limit, int(settings_store.get(s, "x_max_per_run") or 40)))

    def fetch_account(self, s: Session, client, handle: str,
                      since_id: int | None = None,
                      media_only: bool = True) -> list[ScrapedPost]:
        """Monitoring poll (Phase X2): one account's timeline, newest first,
        stopping at the cursor."""
        handle = handle.lstrip("@")
        self.start_url = (f"https://x.com/{handle}/media" if media_only
                          else f"https://x.com/{handle}")
        posts = super().fetch_recent(s, client, limit=10_000)
        wanted = f"@{handle.lower()}"
        posts = [p for p in posts
                 if (p.author or "").lower() == wanted]
        if since_id:
            posts = [p for p in posts if self._tweet_num(p) > int(since_id)]
        return self.apply_scope(s, posts, limit=None)
