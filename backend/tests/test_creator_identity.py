"""Inspiration 2.0 I12 — cross-source creator identity.

The rule under test everywhere here: PF2 links platform identities on
OBSERVABLE evidence and never on a name match (§73), and a link presents
two rows together without ever merging them.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from promptforge import db as db_mod
from promptforge.intel import creator_links as cl
from promptforge.intel import creators as creator_intel
from promptforge.main import create_app
from promptforge.models import Creator, CreatorLink
from tests.conftest import seed_post


def mk(platform: str, handle: str, **kw) -> int:
    with db_mod.session_scope() as s:
        c = Creator(platform=platform, handle=handle, stats={}, **kw)
        s.add(c)
        s.flush()
        return c.id


# --------------------------------------------------------- the safety rule --
def test_identical_handles_alone_never_link(app_env):
    a = mk("x", "mara")
    b = mk("reddit", "mara")
    with db_mod.session_scope() as s:
        assert cl.suggest_links(s) == []
        assert cl.scan(s) == {"linked": 0, "suggested_only": 0, "threshold": 0.75}
        assert s.query(CreatorLink).count() == 0


def test_unknown_evidence_kind_is_refused(app_env):
    a, b = mk("x", "mara"), mk("reddit", "mara_makes")
    with db_mod.session_scope() as s:
        assert cl.record_link(s, a, b, "same_name") is None
        assert cl.record_link(s, a, b, "vibes", "they feel similar") is None
        assert cl.record_link(s, a, a, "user") is None          # not itself
        assert s.query(CreatorLink).count() == 0


# ------------------------------------------------------------- the evidence --
def test_same_media_on_two_platforms_links_them(app_env):
    a = mk("x", "mara")
    b = mk("reddit", "different_name_entirely")
    seed_post(platform="x", creator_id=a, content_hash="deadbeef" * 8)
    seed_post(platform="reddit", creator_id=b, content_hash="deadbeef" * 8)
    with db_mod.session_scope() as s:
        [sug] = cl.suggest_links(s)
        assert sug["kind"] == "same_media" and sug["auto_linkable"]
        assert {sug["creator_a"]["platform"], sug["creator_b"]["platform"]} == {"x", "reddit"}
        out = cl.scan(s)
        assert out["linked"] == 1
        links = cl.links_for(s, a)
        assert links[0]["creator_id"] == b and links[0]["kind"] == "same_media"
        assert "identical media" in links[0]["evidence"]["detail"]
        # idempotent: a second scan does not duplicate the edge
        cl.scan(s)
        assert s.query(CreatorLink).count() == 1


def test_near_duplicate_media_is_weaker_and_not_auto_linked(app_env):
    a, b = mk("x", "mara"), mk("bluesky", "someone.else")
    seed_post(platform="x", creator_id=a, phash="ffffffffffffffff")
    seed_post(platform="bluesky", creator_id=b, phash="fffffffffffffff0")
    with db_mod.session_scope() as s:
        [sug] = cl.suggest_links(s)
        assert sug["kind"] == "near_dup_media" and not sug["auto_linkable"]
        assert cl.scan(s)["linked"] == 0 and cl.scan(s)["suggested_only"] == 1


def test_profile_cross_reference_links_them(app_env):
    a = mk("x", "mara", bio="ai video experiments — also reddit.com/u/mara_makes")
    b = mk("reddit", "mara_makes")
    with db_mod.session_scope() as s:
        [sug] = cl.suggest_links(s)
        assert sug["kind"] == "cross_ref" and sug["auto_linkable"]
        assert "mara_makes" in sug["evidence"]["detail"]


def test_shared_off_platform_site_links_but_a_link_hub_does_not(app_env):
    a = mk("x", "mara", bio="https://mara.studio/work")
    b = mk("bluesky", "m.bsky.social", profile_url="https://www.mara.studio/work/")
    for i in range(6):                      # 7 profiles sharing one linktree
        mk("reddit", f"hub{i}", bio="https://linktr.ee/aiart")
    mk("x", "hubx", bio="https://linktr.ee/aiart")
    with db_mod.session_scope() as s:
        sugs = cl.suggest_links(s)
        kinds = {(s_["creator_a"]["id"], s_["creator_b"]["id"]): s_ for s_ in sugs}
        assert kinds[(min(a, b), max(a, b))]["kind"] == "shared_url"
        # nothing was suggested off the generic link-hub host
        assert all("linktr.ee" not in (s_["evidence"].get("url") or "") for s_ in sugs)


def test_same_platform_is_never_a_cross_source_link(app_env):
    a, b = mk("x", "mara"), mk("x", "mara2")
    seed_post(platform="x", creator_id=a, content_hash="ab" * 32)
    seed_post(platform="x", creator_id=b, content_hash="ab" * 32)
    with db_mod.session_scope() as s:
        assert cl.suggest_links(s) == []


def test_handle_affinity_only_corroborates(app_env):
    """A matching handle raises an existing link's confidence — it can never
    produce one on its own (already covered above)."""
    a = mk("x", "mara_makes", bio="https://mara.studio")
    b = mk("bluesky", "maramakes.bsky.social", profile_url="https://mara.studio")
    c = mk("reddit", "zzz_unrelated", bio="https://mara.studio")
    with db_mod.session_scope() as s:
        by_pair = {(r["creator_a"]["id"], r["creator_b"]["id"]): r
                   for r in cl.suggest_links(s)}
        same = by_pair[(min(a, b), max(a, b))]
        other = by_pair[(min(a, c), max(a, c))]
        assert same["confidence"] > other["confidence"]
        assert other["kind"] == "shared_url"       # still only the URL evidence


# ------------------------------------------------- linked, never merged ----
def test_identity_is_transitive_but_posts_stay_put(app_env):
    a, b, c = mk("x", "mara"), mk("reddit", "mara_makes"), mk("bluesky", "m.bsky.social")
    seed_post(platform="x", creator_id=a)
    seed_post(platform="reddit", creator_id=b)
    seed_post(platform="reddit", creator_id=b)
    seed_post(platform="bluesky", creator_id=c)
    with db_mod.session_scope() as s:
        cl.record_link(s, a, b, "same_media", "identical media", created_by="system")
        cl.record_link(s, b, c, "user", "confirmed in the GUI", created_by="user")
        creator_intel.refresh(s, s.get(Creator, a))
        creator_intel.refresh(s, s.get(Creator, b))
        ident = cl.identity(s, a)
    assert ident["platforms"] == ["bluesky", "reddit", "x"]
    assert ident["total_posts"] == 4 and ident["merged"] is False
    with db_mod.session_scope() as s:
        # posts never moved: each creator still owns exactly what it posted
        assert (s.get(Creator, a).stats["posts"], s.get(Creator, b).stats["posts"]) == (1, 2)
        assert s.get(Creator, a).stats["cross_platform"]["linked_platforms"] == ["reddit"]


def test_user_confirmation_outranks_a_system_guess(app_env):
    a, b = mk("x", "mara"), mk("reddit", "mara_makes")
    with db_mod.session_scope() as s:
        cl.record_link(s, a, b, "shared_url", "both link mara.studio")
        cl.record_link(s, a, b, "user", "I confirmed it", created_by="user")
        [link] = cl.links_for(s, a)
        assert link["confidence"] == 1.0 and link["created_by"] == "user"
        assert link["evidence"]["previous"] == "shared_url"
        assert cl.unlink(s, link["link_id"]) and cl.links_for(s, a) == []


# ------------------------------------------------------------------ stats --
def test_prompt_quality_counts_only_what_the_creator_published(app_env):
    a = mk("x", "mara")
    seed_post(platform="x", creator_id=a, prompt="a lone figure in a neon alley, "
              "35mm anamorphic, volumetric fog, rain-slick street, cinematic grade",
              prompt_source="explicit_caption", negative_prompt="text, watermark",
              params={"seed": 42, "steps": 30}, has_workflow=True)
    seed_post(platform="x", creator_id=a, prompt="a guess an llm made up",
              prompt_source="ai_inference")
    seed_post(platform="x", creator_id=a, prompt="prose that looked prompt-shaped",
              prompt_source="deterministic_inference")
    with db_mod.session_scope() as s:
        st = creator_intel.refresh(s, s.get(Creator, a))
    pq = st["prompt_quality"]
    assert pq["explicit_prompts"] == 1                     # only the published one
    assert pq["with_parameters"] == 1.0 and pq["with_negative"] == 1.0
    assert pq["score"] > 0.5
    assert st["workflow_richness"]["with_workflow"] == 1
    assert {r["source"] for r in st["prompt_sources"]} == {
        "explicit_caption", "ai_inference", "deterministic_inference"}


def test_creator_with_no_observed_prompt_says_so(app_env):
    a = mk("x", "quiet")
    seed_post(platform="x", creator_id=a, prompt=None)
    with db_mod.session_scope() as s:
        st = creator_intel.refresh(s, s.get(Creator, a))
    assert st["prompt_quality"]["explicit_prompts"] == 0
    assert "no prompt this creator published" in st["prompt_quality"]["detail"]


# -------------------------------------------------------------------- API --
def test_identity_api_roundtrip(app_env):
    a, b = mk("x", "mara"), mk("reddit", "mara_makes")
    seed_post(platform="x", creator_id=a, content_hash="cd" * 32)
    seed_post(platform="reddit", creator_id=b, content_hash="cd" * 32)
    client = TestClient(create_app())

    sug = client.get("/api/inspiration/creators/links/suggestions").json()
    assert sug["suggestions"][0]["kind"] == "same_media"
    assert "strangers" in sug["note"]

    assert client.post("/api/inspiration/creators/links",
                       json={"creator_a": a, "creator_b": b, "kind": "same_name"}
                       ).status_code == 422
    r = client.post("/api/inspiration/creators/links",
                    json={"creator_a": a, "creator_b": b, "kind": "user",
                          "detail": "same person"})
    assert r.status_code == 200 and r.json()["confidence"] == 1.0
    link_id = r.json()["link_id"]

    ident = client.get(f"/api/inspiration/creators/{a}/identity").json()
    assert ident["platforms"] == ["reddit", "x"] and ident["merged"] is False
    assert client.get(f"/api/inspiration/creators/{a}").json()["links"][0]["handle"] == "mara_makes"

    assert client.delete(f"/api/inspiration/creators/links/{link_id}").status_code == 200
    assert client.get(f"/api/inspiration/creators/{a}/identity").json()["platforms"] == ["x"]
    assert client.post("/api/inspiration/creators/links/scan").json()["linked"] == 1
