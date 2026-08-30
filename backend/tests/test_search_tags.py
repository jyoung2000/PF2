"""Search API (2.6): free text, qualifiers, filters, collection scope; tags API."""
from tests.conftest import seed_post


def test_search_free_text_ranked(client):
    a = seed_post(prompt="a neon cyberpunk street at night")
    seed_post(prompt="a pastoral watercolor meadow")
    r = client.get("/api/search?q=cyberpunk neon")
    body = r.json()
    assert [it["id"] for it in body["items"]] == [a]
    assert body["total"] == 1


def test_search_model_qualifier(client):
    f = seed_post(prompt="city skyline", model_name="FLUX.1 [dev]", model_family="flux")
    s = seed_post(prompt="city skyline", model_name="SDXL", model_family="sdxl")
    r = client.get("/api/search?q=model:flux city")
    assert [it["id"] for it in r.json()["items"]] == [f]
    # qualifier value goes through alias normalization
    r2 = client.get('/api/search?q=model:"Flux Dev" city')
    assert [it["id"] for it in r2.json()["items"]] == [f]
    r3 = client.get("/api/search?q=model:sdxl")
    assert [it["id"] for it in r3.json()["items"]] == [s]


def test_search_tag_qualifier_and_tags_api(client):
    a = seed_post(prompt="tagged one")
    b = seed_post(prompt="tagged two")
    client.post(f"/api/posts/{a}/tags", json={"name": "Cyberpunk"})
    client.post(f"/api/posts/{b}/tags", json={"name": "pastel"})
    r = client.get("/api/search?q=tag:cyberpunk")
    assert [it["id"] for it in r.json()["items"]] == [a]
    # tag free-text also matches via FTS tags column
    r2 = client.get("/api/search?q=cyberpunk")
    assert [it["id"] for it in r2.json()["items"]] == [a]
    # case-insensitive dedupe of tag names
    client.post(f"/api/posts/{b}/tags", json={"name": "CYBERPUNK"})
    r3 = client.get("/api/search?q=tag:cyberpunk")
    assert sorted(it["id"] for it in r3.json()["items"]) == sorted([a, b])
    # remove + gc
    client.delete(f"/api/posts/{b}/tags/cyberpunk")
    client.delete(f"/api/posts/{a}/tags/Cyberpunk")
    names = [t["name"].lower() for t in client.get("/api/tags").json()["tags"]]
    assert "cyberpunk" not in names


def test_search_filters_and_platform_qualifier(client):
    a = seed_post(prompt="shared subject", platform="civitai")
    b = seed_post(prompt="shared subject", platform="lexica")
    r = client.get("/api/search?q=platform:lexica shared")
    assert [it["id"] for it in r.json()["items"]] == [b]
    r2 = client.get("/api/search?q=shared subject&media_type=image&platform=civitai")
    assert [it["id"] for it in r2.json()["items"]] == [a]


def test_search_collection_scope(client):
    from promptforge import db as db_mod
    from promptforge.models import Collection, CollectionPost
    a = seed_post(prompt="inside the collection")
    seed_post(prompt="inside nothing")
    with db_mod.session_scope() as s:
        c = Collection(name="Test", model_family="flux")
        s.add(c)
        s.flush()
        s.add(CollectionPost(collection_id=c.id, post_id=a))
        cid = c.id
    r = client.get(f"/api/search?q=inside&collection_id={cid}")
    assert [it["id"] for it in r.json()["items"]] == [a]


def test_search_pagination_with_text(client):
    ids = [seed_post(prompt=f"waterfall number {i}") for i in range(5)]
    r = client.get("/api/search?q=waterfall&limit=3")
    body = r.json()
    assert len(body["items"]) == 3 and body["next_cursor"] == 3
    r2 = client.get(f"/api/search?q=waterfall&limit=3&cursor={body['next_cursor']}")
    assert len(r2.json()["items"]) == 2
    assert {it["id"] for it in body["items"]} | \
           {it["id"] for it in r2.json()["items"]} == set(ids)


def test_suggest(client):
    seed_post(model_family="flux", model_name="flux.1-dev")
    a = seed_post(prompt="x")
    client.post(f"/api/posts/{a}/tags", json={"name": "cyberpunk"})
    r = client.get("/api/suggest?q=fl")
    assert any(m["family"] == "flux" for m in r.json()["models"])
    r2 = client.get("/api/suggest?q=cy")
    assert any(t["name"] == "cyberpunk" for t in r2.json()["tags"])


def test_search_empty_and_hostile(client):
    seed_post(prompt="anything")
    assert client.get("/api/search?q=").status_code == 200
    assert client.get('/api/search?q=") OR 1=1 --').status_code == 200
