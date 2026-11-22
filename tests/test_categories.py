"""Category hub: tree endpoint, filters, YouTube thumbnails and the idempotent seed."""
import json

import pytest

from app.media import thumbnail_for, youtube_id
from app.seed import seed

VID = "s_Ntt6eTn94"   # 11-character YouTube video ID

CATALOG = {
    "groups": [{
        "slug": "network", "name": "Network", "icon": "🌐", "description": "Networking",
        "resources": [{"title": "Subnetting", "kind": "video",
                       "links": [{"url": f"https://www.youtube.com/watch?v={VID}", "label": "Subnet"}]}],
        "topics": [{"slug": "ccna", "name": "CCNA", "icon": "🛰",
                    "resources": [{"title": "Packet Tracer", "kind": "tool",
                                   "links": ["https://www.netacad.com/cisco-packet-tracer"]}]}],
    }]
}


@pytest.fixture
def seeded(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG))
    return seed(path), path


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}?t=30",
    f"https://youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://m.youtube.com/watch?feature=share&v={VID}",
])
def test_youtube_id_formats(url):
    assert youtube_id(url) == VID
    assert thumbnail_for(url) == f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"


@pytest.mark.parametrize("url", [
    "https://docs.docker.com", "https://youtu.be/short", "https://www.youtube.com/results?search_query=x",
    "https://evil.com/watch?v=s_Ntt6eTn94",
])
def test_not_a_youtube_video(url):
    assert thumbnail_for(url) is None


def test_seed_is_idempotent(seeded):
    stats, path = seeded
    assert stats == {"categories": 2, "resources": 2, "new_resources": 2}
    again = seed(path)                               # second run: nothing new, nothing duplicated
    assert again["new_resources"] == 0


def test_category_tree(client, seeded):
    groups = client.get("/categories").json()
    assert [g["slug"] for g in groups] == ["network"]
    net = groups[0]
    assert [t["slug"] for t in net["topics"]] == ["ccna"]
    assert net["resource_count"] == 1 and net["total_count"] == 2


def test_filter_by_category_and_thumbnail(client, seeded):
    basics = client.get("/resources?category=network").json()
    assert [r["title"] for r in basics] == ["Subnetting"]
    link = basics[0]["links"][0]
    assert link["label"] == "Subnet"
    assert link["thumbnail_url"] == f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg"

    assert [r["title"] for r in client.get("/resources?category=ccna&kind=tool").json()] == ["Packet Tracer"]
    assert client.get("/resources?category=ccna&kind=video").json() == []
    assert client.get("/resources?category=nope").status_code == 404


def test_share_into_category(client, make_user, seeded):
    headers = make_user("a@x.com")
    body = {"title": "My CCNA notes", "kind": "video", "category": "ccna",
            "description": "  short labs  ", "links": [f"https://youtu.be/{VID}"]}
    created = client.post("/resources", json=body, headers=headers)
    assert created.status_code == 201
    out = created.json()
    assert out["category"] == {"slug": "ccna", "name": "CCNA"}
    assert out["description"] == "short labs"
    assert out["links"][0]["thumbnail_url"].endswith(f"/{VID}/hqdefault.jpg")

    bad = client.post("/resources", json={**body, "category": "nope"}, headers=headers)
    assert bad.status_code == 422
    assert client.post("/resources", json={**body, "kind": "meme"}, headers=headers).status_code == 422
