"""Link helpers: recognise YouTube videos and build their thumbnail URL.

No network call is needed: YouTube serves every video's thumbnail at a fixed address,
https://i.ytimg.com/vi/<video-id>/hqdefault.jpg
"""
import re
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")      # YouTube video IDs are always 11 of these characters


def youtube_id(url: str) -> str | None:
    try:
        u = urlparse(url)
    except ValueError:
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate = None
    if host == "youtu.be":
        candidate = u.path.lstrip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            candidate = parse_qs(u.query).get("v", [None])[0]
        else:
            parts = u.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                candidate = parts[1]
    return candidate if candidate and _ID.match(candidate) else None


def thumbnail_for(url: str) -> str | None:
    vid = youtube_id(url)
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None
