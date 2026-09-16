"""X (Twitter) parser — public posts only.

Primary: syndication embed API (same idea as yt-dlp / react-tweet)
Fallback: fxtwitter → vxtwitter → yt-dlp (twitter extractor only)

Isolated from Bilibili / Douyin / YouTube code paths.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from backend.httputil import format_count, format_duration

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# yt-dlp uses Googlebot for syndication — some posts only answer to it.
BOT_UA = "Googlebot"

# Match any x.com / twitter.com status URL, including:
#   /user/status/ID
#   /i/status/ID
#   /i/web/status/ID
#   /user/status/ID/video/1
STATUS_RE = re.compile(
    r"(?:twitter\.com|x\.com)/.*?/(?:status|statuses)/(\d{5,})",
    re.I,
)
DIM_RE = re.compile(r"/(\d{2,5})x(\d{2,5})/")
_TCO_RE = re.compile(r"https?://t\.co/\w+", re.I)
_MP4_RE = re.compile(r"https?://[^\s\"'<>\\]+?\.mp4[^\s\"'<>\\]*", re.I)


def _clean_text(text: Any) -> str:
    if isinstance(text, dict):
        text = text.get("text") or text.get("content") or ""
    text = _TCO_RE.sub("", str(text or "")).strip()
    return re.sub(r"\s+", " ", text).strip() or "X 视频"


def is_twitter(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return (
        host == "x.com"
        or host.endswith(".x.com")
        or host == "twitter.com"
        or host.endswith(".twitter.com")
        or host == "t.co"
        or host.endswith(".t.co")
    )


def _browser_headers() -> dict:
    return {
        "User-Agent": PC_UA,
        "Accept": "application/json,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Referer": "https://x.com/",
    }


def _bot_headers() -> dict:
    return {
        "User-Agent": BOT_UA,
        "Accept": "application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _cdn_headers() -> dict:
    return {
        "User-Agent": PC_UA,
        "Referer": "https://x.com/",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _syndication_token(tweet_id: str) -> str:
    """Same algorithm as yt-dlp / Vercel react-tweet."""
    try:
        from yt_dlp.jsinterp import js_number_to_string

        translation = str.maketrans(dict.fromkeys("0."))
        return js_number_to_string((int(tweet_id) / 1e15) * math.pi, 36).translate(translation)
    except Exception:
        # Minimal fallback if yt_dlp import path changes
        n = (int(tweet_id) / 1e15) * math.pi
        alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
        whole = int(abs(n))
        frac = abs(n) - whole
        s = ""
        if whole == 0:
            s = "0"
        else:
            while whole:
                whole, rem = divmod(whole, 36)
                s = alphabet[rem] + s
        if frac:
            s += "."
            for _ in range(24):
                frac *= 36
                digit = int(frac)
                s += alphabet[digit]
                frac -= digit
                if frac < 1e-14:
                    break
        return "".join(ch for ch in s if ch not in "0.")


def _extract_status_id(url: str) -> Optional[str]:
    m = STATUS_RE.search(url or "")
    if m:
        return m.group(1)
    # bare numeric path leftovers
    m2 = re.search(r"/(\d{15,20})(?:[/?#]|$)", url or "")
    if m2 and ("status" in (url or "").lower() or "twitter" in (url or "").lower() or "x.com" in (url or "").lower()):
        return m2.group(1)
    return None


def _resolve(url: str) -> tuple[str, str]:
    direct = _extract_status_id(url)
    if direct:
        return direct, url

    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=_browser_headers()) as client:
            res = client.get(url)
            final = str(res.url)
            found = _extract_status_id(final) or _extract_status_id(res.text)
            if found:
                return found, final
    except httpx.HTTPError as e:
        raise HTTPException(status_code=422, detail=f"X 链接跳转失败：{e}") from e

    raise HTTPException(
        status_code=422,
        detail="无法识别 X 帖子 ID。请粘贴 https://x.com/用户名/status/数字 这类链接。",
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _height_from_url(media_url: str) -> int:
    """Return display height from .../WIDTHxHEIGHT/... path (works for vertical too)."""
    m = DIM_RE.search(media_url or "")
    if not m:
        return 0
    w, h = _safe_int(m.group(1), 0), _safe_int(m.group(2), 0)
    # For labels like 720p, use the larger side for portrait clips.
    return max(w, h) if w and h else (h or w)


def _add_mp4(out: list[dict], src: str, height: int = 0, bitrate: int = 0) -> None:
    src = (src or "").strip().replace("&amp;", "&")
    if not src or ".mp4" not in src.lower():
        return
    if not src.startswith("http"):
        return
    if any(x.get("url") == src for x in out):
        return
    out.append(
        {
            "url": src,
            "height": height or _height_from_url(src),
            "bitrate": _safe_int(bitrate, 0),
        }
    )


def _walk_mp4s(obj: Any, out: list[dict]) -> None:
    """Recursively collect any progressive MP4 URLs from nested JSON."""
    if isinstance(obj, dict):
        # Prefer structured variants when present
        if "variants" in obj and isinstance(obj["variants"], list):
            for v in obj["variants"]:
                if not isinstance(v, dict):
                    continue
                src = v.get("src") or v.get("url") or ""
                ctype = str(v.get("type") or v.get("content_type") or "").lower()
                if "mp4" in ctype or ".mp4" in src.lower():
                    _add_mp4(out, src, _height_from_url(src), v.get("bitrate") or 0)
        for v in obj.values():
            _walk_mp4s(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_mp4s(v, out)
    elif isinstance(obj, str):
        for m in _MP4_RE.findall(obj):
            _add_mp4(out, m.rstrip("),.;'\""), _height_from_url(m), 0)


def _from_syndication(status_id: str) -> Optional[dict]:
    token = _syndication_token(status_id)
    api = "https://cdn.syndication.twimg.com/tweet-result"
    params = {"id": status_id, "lang": "en", "token": token}
    # Try bot UA first (yt-dlp), then browser UA
    for headers in (_bot_headers(), _browser_headers()):
        try:
            with httpx.Client(follow_redirects=True, timeout=25.0, headers=headers) as client:
                res = client.get(api, params=params)
                if res.status_code != 200 or not res.content:
                    continue
                data = res.json()
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            continue
    return None


def _from_fxtwitter(status_id: str) -> Optional[dict]:
    for base in (
        f"https://api.fxtwitter.com/status/{status_id}",
        f"https://api.vxtwitter.com/status/{status_id}",
    ):
        try:
            with httpx.Client(follow_redirects=True, timeout=25.0, headers=_browser_headers()) as client:
                res = client.get(base)
                if res.status_code != 200 or not res.content:
                    continue
                data = res.json()
                if not isinstance(data, dict):
                    continue
                # fxtwitter: { code, tweet }; some mirrors return tweet at top
                tweet = data.get("tweet") if isinstance(data.get("tweet"), dict) else data
                if isinstance(tweet, dict) and (tweet.get("media") or tweet.get("id") or tweet.get("text")):
                    return tweet
        except Exception:
            continue
    return None


def _meta_from_syndication(data: dict, status_id: str, webpage: str) -> dict:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    text = _clean_text(data.get("text") or data.get("full_text") or "X 视频")
    video = data.get("video") if isinstance(data.get("video"), dict) else {}
    dur_ms = video.get("durationMs") or 0
    try:
        dur = float(dur_ms) / 1000.0 if dur_ms else 0.0
    except (TypeError, ValueError):
        dur = 0.0
    # duration from mediaDetails
    if not dur:
        for md in data.get("mediaDetails") or []:
            if isinstance(md, dict):
                vi = md.get("video_info") or {}
                ms = vi.get("duration_millis") or vi.get("durationMs")
                if ms:
                    try:
                        dur = float(ms) / 1000.0
                        break
                    except (TypeError, ValueError):
                        pass
    thumb = video.get("poster")
    if not thumb:
        for md in data.get("mediaDetails") or []:
            if isinstance(md, dict) and (md.get("media_url_https") or md.get("media_url")):
                thumb = md.get("media_url_https") or md.get("media_url")
                break
    if not thumb:
        photos = data.get("photos") or []
        if photos and isinstance(photos[0], dict):
            thumb = photos[0].get("url") or photos[0].get("src")
    screen = user.get("screen_name") or user.get("screenName") or "user"
    return {
        "id": status_id,
        "title": text[:120] or f"X status {status_id}",
        "author": user.get("name") or screen,
        "likes": format_count(data.get("favorite_count") or data.get("favoriteCount")),
        "views": format_count(video.get("viewCount") or data.get("views") or data.get("view_count")),
        "duration": format_duration(dur),
        "description": text[:240] or "暂无简介",
        "thumbnail": thumb,
        "webpage": webpage if "status" in webpage else f"https://x.com/{screen}/status/{status_id}",
    }


def _meta_from_fxtwitter(tweet: dict, status_id: str, webpage: str) -> dict:
    author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    text = _clean_text(tweet.get("text") or tweet.get("raw_text") or "X 视频")
    media = tweet.get("media") if isinstance(tweet.get("media"), dict) else {}
    videos = media.get("videos") or []
    dur = 0.0
    thumb = None
    if videos and isinstance(videos[0], dict):
        try:
            dur = float(videos[0].get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        thumb = videos[0].get("thumbnail_url")
    screen = author.get("screen_name") or author.get("username") or "user"
    return {
        "id": str(tweet.get("id") or status_id),
        "title": text[:120] or f"X status {status_id}",
        "author": author.get("name") or screen,
        "likes": format_count(tweet.get("likes")),
        "views": format_count(tweet.get("views")),
        "duration": format_duration(dur),
        "description": text[:240] or "暂无简介",
        "thumbnail": thumb,
        "webpage": tweet.get("url") or (webpage if "status" in webpage else f"https://x.com/{screen}/status/{status_id}"),
    }


def _from_ytdlp(url: str, status_id: str) -> Optional[tuple[list[dict], dict]]:
    try:
        import yt_dlp
    except ImportError:
        return None

    page = url if _extract_status_id(url) else f"https://x.com/i/status/{status_id}"
    for api in ("syndication", None, "graphql"):
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "cachedir": False,
            "socket_timeout": 30,
            "http_headers": {"User-Agent": BOT_UA, "Referer": "https://x.com/"},
        }
        if api:
            opts["extractor_args"] = {"twitter": {"api": [api]}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(page, download=False)
        except Exception:
            continue
        if not info:
            continue
        variants: list[dict] = []
        for fmt in info.get("formats") or []:
            if not isinstance(fmt, dict):
                continue
            src = fmt.get("url") or ""
            # Prefer progressive HTTP MP4 for browser preview
            if ".mp4" in src.lower() and "m3u8" not in src.lower():
                _add_mp4(variants, src, _safe_int(fmt.get("height"), 0), fmt.get("tbr") or fmt.get("vbr") or 0)
        if not variants and info.get("url") and ".mp4" in str(info.get("url")).lower():
            _add_mp4(variants, str(info["url"]), _safe_int(info.get("height"), 0), 0)
        if not variants:
            continue
        meta = {
            "id": str(info.get("id") or status_id),
            "title": _clean_text(info.get("title") or info.get("description") or f"X status {status_id}")[:120],
            "author": info.get("uploader") or info.get("creator") or info.get("channel") or "-",
            "likes": format_count(info.get("like_count")),
            "views": format_count(info.get("view_count") or info.get("repost_count")),
            "duration": format_duration(info.get("duration") or 0),
            "description": _clean_text(info.get("description") or info.get("title") or "暂无简介")[:240],
            "thumbnail": info.get("thumbnail"),
            "webpage": info.get("webpage_url") or page,
        }
        return variants, meta
    return None


def _pick_variant(variants: list[dict], quality: str) -> dict:
    if not variants:
        raise HTTPException(status_code=422, detail="该帖子没有可下载的视频")
    height = None
    if quality and quality.endswith("p") and quality[:-1].isdigit():
        height = int(quality[:-1])
    ranked = sorted(
        variants,
        key=lambda v: (_safe_int(v.get("height"), 0), _safe_int(v.get("bitrate"), 0)),
        reverse=True,
    )
    if height:
        capped = [v for v in ranked if _safe_int(v.get("height"), 0) <= height]
        if capped:
            return capped[0]
    return ranked[0]


def parse(url: str) -> dict:
    notes: list[str] = []
    try:
        status_id, final = _resolve(url)
        variants: list[dict] = []
        meta: Optional[dict] = None

        syn = _from_syndication(status_id)
        if syn:
            typename = str(syn.get("__typename") or "")
            # Sensitive / age-gated posts often come back as TweetTombstone on
            # syndication, but fxtwitter can still return progressive MP4s.
            if "Tombstone" in typename or syn.get("tombstone"):
                notes.append("syndication不可用(敏感/限制)")
            else:
                variants = []
                _walk_mp4s(syn, variants)
                if variants:
                    meta = _meta_from_syndication(syn, status_id, final)
                else:
                    notes.append("syndication无MP4")
        else:
            notes.append("syndication无数据")

        if not variants:
            fx = _from_fxtwitter(status_id)
            if fx:
                variants = []
                _walk_mp4s(fx, variants)
                # also structured media.videos
                media = fx.get("media") if isinstance(fx.get("media"), dict) else {}
                for vid in (media.get("videos") or media.get("all") or []):
                    if not isinstance(vid, dict):
                        continue
                    _add_mp4(variants, vid.get("url") or "", _safe_int(vid.get("height"), 0), 0)
                    for fmt in vid.get("formats") or vid.get("variants") or []:
                        if isinstance(fmt, dict):
                            _add_mp4(
                                variants,
                                fmt.get("url") or "",
                                _height_from_url(fmt.get("url") or "") or _safe_int(vid.get("height"), 0),
                                fmt.get("bitrate") or 0,
                            )
                if variants:
                    meta = _meta_from_fxtwitter(fx, status_id, final)
                else:
                    notes.append("镜像接口无MP4")
            else:
                notes.append("镜像接口失败")

        if not variants:
            ytdlp_hit = _from_ytdlp(final, status_id)
            if ytdlp_hit:
                variants, meta = ytdlp_hit
            else:
                notes.append("yt-dlp失败")

        if not variants or not meta:
            hint = "；".join(notes) if notes else "未知原因"
            raise HTTPException(
                status_code=422,
                detail=(
                    "X 视频解析失败。请确认：1) 帖子公开；2) 帖子内是原生视频/GIF（不是外链卡片）；"
                    f"3) 链接含 /status/数字。详情：{hint}"
                ),
            )

        qualities: list[str] = []
        for v in sorted(variants, key=lambda x: _safe_int(x.get("height"), 0), reverse=True):
            h = _safe_int(v.get("height"), 0)
            label = f"{h}p" if h else "origin"
            if label not in qualities:
                qualities.append(label)
        if not qualities:
            qualities = ["origin"]

        best = _pick_variant(variants, qualities[0])
        item = {
            "id": str(meta["id"]),
            "index": 1,
            "title": meta["title"],
            "author": meta["author"],
            "views": meta["views"],
            "likes": meta["likes"],
            "duration": meta["duration"],
            "description": meta["description"],
            "thumbnail": meta["thumbnail"],
            "downloadUrl": "",
            "webpageUrl": meta["webpage"],
        }
        return {
            "kind": "video",
            "platform": "X",
            "qualities": qualities,
            "defaultQuality": qualities[0],
            "item": item,
            "sourceUrl": meta["webpage"],
            "_play": best["url"],
            "_variants": variants,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"X 解析失败：{type(e).__name__}: {str(e)[:160]}",
        ) from e


def pick_media(url: str, quality: str) -> dict:
    result = parse(url)
    variants = result.get("_variants") or []
    chosen = _pick_variant(variants, quality) if variants else None
    media = (chosen or {}).get("url") or result.get("_play")
    if not media:
        raise HTTPException(status_code=422, detail="X 没有可下载地址")
    status_id = result["item"]["id"]
    h = _safe_int((chosen or {}).get("height"), 0)
    filename = f"x-{status_id}{('-' + str(h) + 'p') if h else ''}.mp4"
    return {
        "media_url": media,
        "headers": _cdn_headers(),
        "filename": filename,
        "ext": "mp4",
    }
