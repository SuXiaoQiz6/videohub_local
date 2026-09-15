from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Optional
from urllib.parse import urlparse
from pathlib import Path
import yt_dlp

app = FastAPI(title="VideoHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_HOSTS = (
    "bilibili.com",
    "b23.tv",
    "douyin.com",
    "iesdouyin.com",
    "youtube.com",
    "youtu.be",
)


class ParseRequest(BaseModel):
    url: str = Field(..., min_length=1)


def _host_ok(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in SUPPORTED_HOSTS)


def _platform_name(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "bilibili" in host or "b23.tv" in host:
        return "Bilibili"
    if "douyin" in host:
        return "抖音"
    if "youtube" in host or "youtu.be" in host:
        return "YouTube"
    return "Unknown"


def _format_count(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _format_duration(seconds: Any) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return "00:00"
    m, sec = divmod(max(s, 0), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def _quality_label(fmt: dict) -> Optional[str]:
    height = fmt.get("height")
    if height:
        return f"{height}p"
    note = (fmt.get("format_note") or "").lower()
    for q in ("2160", "1440", "1080", "720", "480", "360", "240"):
        if q in note:
            return f"{q}p"
    return None


def _collect_qualities(info: dict) -> list[str]:
    seen = []
    for fmt in info.get("formats") or []:
        # Prefer progressive or video streams with height
        if fmt.get("vcodec") in (None, "none"):
            continue
        label = _quality_label(fmt)
        if label and label not in seen:
            seen.append(label)
    # Sort high → low by numeric height
    def key(q: str) -> int:
        try:
            return int(q.rstrip("p"))
        except ValueError:
            return 0

    seen.sort(key=key, reverse=True)
    return seen or ["best"]


def _collect_audio_formats(info: dict) -> list[str]:
    exts = []
    for fmt in info.get("formats") or []:
        if fmt.get("acodec") in (None, "none"):
            continue
        if fmt.get("vcodec") not in (None, "none"):
            continue
        ext = (fmt.get("ext") or "").lower()
        if ext and ext not in exts:
            exts.append(ext)
    # Common preferred order for UI
    preferred = ["mp3", "m4a", "webm", "opus", "ogg", "wav"]
    ordered = [e for e in preferred if e in exts]
    for e in exts:
        if e not in ordered:
            ordered.append(e)
    return ordered or ["m4a", "mp3"]


def _pick_download_url(info: dict, prefer_audio: bool = False) -> Optional[str]:
    if info.get("url") and not info.get("formats"):
        return info.get("url")
    formats = info.get("formats") or []
    if prefer_audio:
        audio = [
            f
            for f in formats
            if f.get("acodec") not in (None, "none")
            and f.get("vcodec") in (None, "none")
            and f.get("url")
        ]
        if audio:
            audio.sort(key=lambda f: f.get("abr") or 0, reverse=True)
            return audio[0].get("url")
    # Prefer a progressive http(s) URL with both a/v when possible
    progressive = [
        f
        for f in formats
        if f.get("url")
        and f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
    ]
    if progressive:
        progressive.sort(key=lambda f: f.get("height") or 0, reverse=True)
        return progressive[0].get("url")
    # Fallback: best video-only / any with url
    with_url = [f for f in formats if f.get("url")]
    if with_url:
        with_url.sort(key=lambda f: f.get("height") or f.get("abr") or 0, reverse=True)
        return with_url[0].get("url")
    return info.get("url")


def _entry_to_item(entry: dict, index: int) -> dict:
    eid = entry.get("id") or entry.get("url") or f"item-{index}"
    return {
        "id": str(eid),
        "index": index,
        "title": entry.get("title") or f"条目 {index}",
        "author": entry.get("uploader")
        or entry.get("channel")
        or entry.get("creator")
        or "-",
        "views": _format_count(entry.get("view_count")),
        "likes": _format_count(entry.get("like_count")),
        "duration": _format_duration(entry.get("duration")),
        "description": (entry.get("description") or "")[:240]
        or "暂无简介",
        "thumbnail": entry.get("thumbnail"),
        "downloadUrl": _pick_download_url(entry)
        or entry.get("webpage_url")
        or entry.get("url")
        or "",
        "webpageUrl": entry.get("webpage_url") or entry.get("url") or "",
    }


def _extract(url: str) -> dict:
    host = (urlparse(url).hostname or "").lower()
    referer = "https://www.bilibili.com/"
    if "douyin" in host:
        referer = "https://www.douyin.com/"
    elif "youtube" in host or "youtu.be" in host:
        referer = "https://www.youtube.com/"

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "cachedir": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        "extractor_args": {
            "youtube": {"player_client": ["android", "web"]},
        },
    }

    # Optional: put Netscape cookies.txt next to backend to unlock Bilibili/Douyin
    # Export via browser extension "Get cookies.txt LOCALLY", save as backend/cookies.txt
    cookies_path = Path(__file__).resolve().parent / "cookies.txt"
    if cookies_path.is_file():
        ydl_opts["cookiefile"] = str(cookies_path)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise HTTPException(status_code=422, detail="解析失败：未获取到媒体信息")
    return info


def _build_result(url: str, info: dict) -> dict:
    platform = _platform_name(url)
    entries = info.get("entries")
    # Playlist / collection
    if entries:
        items = []
        for i, entry in enumerate(entries, start=1):
            if not entry:
                continue
            # Flat entries may need a second extract for formats — keep lightweight for MVP list
            items.append(_entry_to_item(entry, i))
        if not items:
            raise HTTPException(status_code=422, detail="合集为空或无法读取条目")

        # Resolve current item: match requested URL / original id
        current_id = str(info.get("id") or items[0]["id"])
        matched = None
        for it in items:
            if it["webpageUrl"] and it["webpageUrl"].rstrip("/") == url.rstrip("/"):
                matched = it
                break
            if it["id"] == str(info.get("id")):
                matched = it
                break
        if matched is None:
            # bilibili ?p=N often embeds page index in URL
            matched = items[0]
            try:
                from urllib.parse import parse_qs

                qs = parse_qs(urlparse(url).query)
                if "p" in qs:
                    p = int(qs["p"][0])
                    if 1 <= p <= len(items):
                        matched = items[p - 1]
            except Exception:
                pass

        # Enrich current entry with full metadata if flat
        if not matched.get("downloadUrl") or matched.get("downloadUrl") == matched.get(
            "webpageUrl"
        ):
            try:
                detail = _extract(matched["webpageUrl"] or url)
                if detail.get("entries"):
                    # still a playlist wrapper — use first real
                    detail = detail
                else:
                    enriched = _entry_to_item(detail, matched["index"])
                    matched.update(
                        {
                            "title": enriched["title"],
                            "author": enriched["author"],
                            "views": enriched["views"],
                            "likes": enriched["likes"],
                            "duration": enriched["duration"],
                            "description": enriched["description"],
                            "thumbnail": enriched["thumbnail"],
                            "downloadUrl": enriched["downloadUrl"],
                        }
                    )
                    # Update in items list
                    for i, it in enumerate(items):
                        if it["id"] == matched["id"]:
                            items[i] = matched
                            break
                    qualities = _collect_qualities(detail)
                    return {
                        "kind": "collection",
                        "platform": platform,
                        "collectionName": info.get("title")
                        or info.get("playlist_title")
                        or "合集",
                        "collectionCount": len(items),
                        "parsedId": matched["id"],
                        "qualities": qualities,
                        "defaultQuality": qualities[0] if qualities else "best",
                        "items": items,
                        "sourceUrl": url,
                    }
            except Exception:
                pass

        qualities = _collect_qualities(info) or ["1080p", "720p", "480p"]
        return {
            "kind": "collection",
            "platform": platform,
            "collectionName": info.get("title")
            or info.get("playlist_title")
            or "合集",
            "collectionCount": len(items),
            "parsedId": matched["id"],
            "qualities": qualities,
            "defaultQuality": qualities[0] if qualities else "best",
            "items": items,
            "sourceUrl": url,
        }

    # Single media
    is_audio = (info.get("vcodec") in (None, "none")) and (
        info.get("acodec") not in (None, "none")
    )
    # Heuristic: youtube audio-only request or no video formats
    formats = info.get("formats") or []
    has_video = any(f.get("vcodec") not in (None, "none") for f in formats)
    if not has_video and formats:
        is_audio = True

    item = _entry_to_item(info, 1)
    if is_audio or platform == "YouTube" and "audio" in (info.get("title") or "").lower():
        # Keep YouTube as video unless clearly audio-only
        pass

    if is_audio:
        fmts = _collect_audio_formats(info)
        return {
            "kind": "audio",
            "platform": platform,
            "formats": fmts,
            "defaultFormat": fmts[0],
            "item": item,
            "sourceUrl": url,
        }

    qualities = _collect_qualities(info)
    return {
        "kind": "video",
        "platform": platform,
        "qualities": qualities,
        "defaultQuality": qualities[0] if qualities else "best",
        "item": item,
        "sourceUrl": url,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "videohub"}


@app.post("/api/parse")
def parse(body: ParseRequest):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="请输入想要解析的音视频资源链接")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="URL 格式错误。请输入 B 站、抖音或 YouTube 的音视频页面链接。",
        )
    if not _host_ok(url):
        raise HTTPException(
            status_code=400,
            detail="暂不支持该平台。MVP 仅支持 B 站、抖音、YouTube。",
        )
    try:
        info = _extract(url)
        return {"ok": True, "result": _build_result(url, info)}
    except HTTPException:
        raise
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).split("\n")[0][:200]
        raise HTTPException(status_code=422, detail=f"解析失败：{msg}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析异常：{type(e).__name__}")


@app.post("/api/resolve-item")
def resolve_item(body: ParseRequest):
    """Enrich a single collection entry URL with download formats (on demand)."""
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="缺少条目 URL")
    try:
        info = _extract(url)
        if info.get("entries"):
            # pick first
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise HTTPException(status_code=422, detail="无法解析该条目")
            info = entries[0]
            # If still flat, extract webpage
            if not info.get("formats") and info.get("url"):
                info = _extract(info.get("webpage_url") or info["url"])
        item = _entry_to_item(info, 1)
        qualities = _collect_qualities(info)
        return {
            "ok": True,
            "item": item,
            "qualities": qualities,
            "defaultQuality": qualities[0] if qualities else "best",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"条目解析失败：{e}")
