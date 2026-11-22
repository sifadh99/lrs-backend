"""Check every link in seed/catalog.json before it goes into the database.

- normal links: must answer (2xx/3xx; some sites refuse bots with 403, those are reported)
- YouTube videos: checked with YouTube's official oEmbed API; the real title/channel
  is written into catalog.json as the link label, so we never show a wrong title.

Run:  python seed/verify_catalog.py          (dev tool, needs internet)
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).with_name("catalog.json")
UA = {"User-Agent": "Mozilla/5.0 (link-checker)"}


def status(url: str) -> int:
    if not url.startswith("https://"):          # never let file:// or ftp:// reach urlopen
        raise ValueError(f"only https links are allowed: {url}")
    req = urllib.request.Request(url, headers=UA)  # noqa: S310 - scheme checked above
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - fixed https URLs from our catalog
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def youtube_oembed(url: str) -> dict | None:
    q = urllib.parse.urlencode({"format": "json", "url": url})
    req = urllib.request.Request(f"https://www.youtube.com/oembed?{q}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
            return json.load(r)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    data = json.loads(CATALOG.read_text())
    bad = 0
    for g in data["groups"]:
        for scope in [g, *g["topics"]]:
            for res in scope["resources"]:
                fixed = []
                for link in res["links"]:
                    url = link if isinstance(link, str) else link["url"]
                    entry = {"url": url}
                    if "youtube.com/watch" in url or "youtu.be/" in url:
                        meta = youtube_oembed(url)
                        if meta:
                            entry["label"] = f'{meta["title"]} · {meta["author_name"]}'
                            print(f"  OK  video  {url}\n             {entry['label']}")
                        else:
                            bad += 1
                            print(f"  BAD video  {url}")
                    else:
                        code = status(url)
                        mark = "OK " if 200 <= code < 400 else "???"
                        if mark != "OK ":
                            bad += 1
                        print(f"  {mark} {code:>3}    {url}")
                    fixed.append(entry)
                res["links"] = fixed
    CATALOG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{bad} link(s) need a look")
    return 0


if __name__ == "__main__":
    sys.exit(main())
