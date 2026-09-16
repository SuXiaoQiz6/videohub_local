"""YouTube and generic fallback via yt-dlp (鱼皮通用引擎).

YouTube 会定期封杀特定 player client。本机实测：
  - player_client=tv / default → 「The page needs to be reloaded」
  - player_client=android → 可拿到至少 360p 渐进 MP4（浏览器可播）

不在产品路径里要求用户导出 cookies.txt；仅当存在 backend/cookies.txt 时作为可选增强。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import HTTPException

from backend.httputil import format_count, format_duration

COOKIES_FILE = Path(__file__).resolve().parent / "cookies.txt"

# Prefer clients that still work without cookies on current yt-dlp (Py3.9 pin ≤2025.10.14).
# tv / default → 「The page needs to be reloaded」; android_vr → up to 1080p + progressive 360p.
_YOUTUBE_CLIENT_TRIES: tuple[tuple[str, ...], ...] = (
    ("android_vr", "android"),
    ("android_vr",),
    ("android",),
    ("android", "web_embedded"),
)


def _base_opts(player_clients: Optional[tuple[str, ...]] = None) -> dict:
    opts = {
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
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        "socket_timeout": 25,
    }
    if player_clients:
        opts["extractor_args"] = {
            "youtube": {"player_client": list(player_clients)},
        }
    return opts


def _cookie_extras() -> list[dict]:
    # Optional only — never block the Chrome Cookie DB while the browser is open.
    if COOKIES_FILE.is_file():
        return [{"cookiefile": str(COOKIES_FILE)}, {}]
    return [{}]


def _attempt_configs() -> list[dict]:
    configs: list[dict] = []
    for clients in _YOUTUBE_CLIENT_TRIES:
        for cookie_extra in _cookie_extras():
            opts = _base_opts(clients)
            opts.update(cookie_extra)
            configs.append(opts)
    # Last resort: yt-dlp defaults (no forced client)
    for cookie_extra in _cookie_extras():
        opts = _base_opts(None)
        opts.update(cookie_extra)
        configs.append(opts)
    return configs


def extract(url: str) -> dict:
    last_err: Optional[Exception] = None
    seen_keys = set()
    for opts in _attempt_configs():
        key = (
            tuple((opts.get("extractor_args") or {}).get("youtube", {}).get("player_client") or ()),
            opts.get("cookiefile") or "",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info and (info.get("formats") or info.get("entries") or info.get("url")):
                return info
        except Exception as e:
            last_err = e
            continue
    err = str(last_err or "未知错误").split("\n")[0][:180]
    raise HTTPException(
        status_code=422,
        detail=(
            "YouTube 解析失败。公开视频一般无需登录；若持续失败可能是平台风控或需更新 yt-dlp。"
            f" 原始错误：{err}"
        ),
    )


def _quality_label(fmt: dict) -> Optional[str]:
    height = fmt.get("height")
    if height:
        return f"{height}p"
    return None


def collect_qualities(info: dict) -> list[str]:
    seen: list[str] = []
    for fmt in info.get("formats") or []:
        if fmt.get("vcodec") in (None, "none"):
            continue
        label = _quality_label(fmt)
        if label and label not in seen:
            seen.append(label)

    def key(q: str) -> int:
        try:
            return int(q.rstrip("p"))
        except ValueError:
            return 0

    seen.sort(key=key, reverse=True)
    return seen or ["best"]


def collect_audio_formats(info: dict) -> list[str]:
    exts = []
    for fmt in info.get("formats") or []:
        if fmt.get("acodec") in (None, "none"):
            continue
        if fmt.get("vcodec") not in (None, "none"):
            continue
        ext = (fmt.get("ext") or "").lower()
        if ext and ext not in exts:
            exts.append(ext)
    preferred = ["m4a", "mp3", "webm", "opus"]
    ordered = [e for e in preferred if e in exts]
    for e in exts:
        if e not in ordered:
            ordered.append(e)
    return ordered or ["m4a"]


def entry_to_item(entry: dict, index: int) -> dict:
    eid = entry.get("id") or entry.get("url") or f"item-{index}"
    return {
        "id": str(eid),
        "index": index,
        "title": entry.get("title") or f"条目 {index}",
        "author": entry.get("uploader")
        or entry.get("channel")
        or entry.get("creator")
        or "-",
        "views": format_count(entry.get("view_count")),
        "likes": format_count(entry.get("like_count")),
        "duration": format_duration(entry.get("duration")),
        "description": (entry.get("description") or "")[:240] or "暂无简介",
        "thumbnail": entry.get("thumbnail"),
        "downloadUrl": "",
        "webpageUrl": entry.get("webpage_url") or entry.get("url") or "",
    }


def build_result(url: str, info: dict, platform: str) -> dict:
    entries = info.get("entries")
    if entries:
        items = []
        for i, entry in enumerate(entries, start=1):
            if not entry:
                continue
            items.append(entry_to_item(entry, i))
        if not items:
            raise HTTPException(status_code=422, detail="合集为空或无法读取条目")
        matched = items[0]
        for it in items:
            if it["webpageUrl"] and it["webpageUrl"].rstrip("/") == url.rstrip("/"):
                matched = it
                break
        qualities = collect_qualities(info) or ["1080p", "720p"]
        return {
            "kind": "collection",
            "platform": platform,
            "collectionName": info.get("title") or info.get("playlist_title") or "合集",
            "collectionCount": len(items),
            "parsedId": matched["id"],
            "qualities": qualities,
            "defaultQuality": qualities[0],
            "items": items,
            "sourceUrl": url,
        }

    formats = info.get("formats") or []
    has_video = any(f.get("vcodec") not in (None, "none") for f in formats)
    item = entry_to_item(info, 1)
    if formats and not has_video:
        fmts = collect_audio_formats(info)
        return {
            "kind": "audio",
            "platform": platform,
            "formats": fmts,
            "defaultFormat": fmts[0],
            "item": item,
            "sourceUrl": url,
        }
    qualities = collect_qualities(info)
    return {
        "kind": "video",
        "platform": platform,
        "qualities": qualities,
        "defaultQuality": qualities[0] if qualities else "best",
        "item": item,
        "sourceUrl": url,
    }


def pick_media(url: str, quality: str, audio: bool = False, audio_format: Optional[str] = None) -> dict:
    """Pick a playable HTTP URL (prefer progressive A+V) for browser <video> / proxy."""
    info = extract(url)
    formats = [f for f in (info.get("formats") or []) if f.get("url")]
    title = (info.get("title") or "video").strip() or "video"
    http_headers = dict((_base_opts().get("http_headers") or {}))
    if info.get("http_headers"):
        http_headers.update(info["http_headers"])

    chosen = None
    if audio:
        audio_fs = [
            f
            for f in formats
            if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
        ]
        if audio_format:
            prefer = [f for f in audio_fs if (f.get("ext") or "") == audio_format]
            audio_fs = prefer or audio_fs
        audio_fs.sort(key=lambda f: f.get("abr") or 0, reverse=True)
        chosen = audio_fs[0] if audio_fs else None
    else:
        height = None
        if quality and quality.endswith("p") and quality[:-1].isdigit():
            height = int(quality[:-1])
        prog = [
            f
            for f in formats
            if f.get("vcodec") not in (None, "none")
            and f.get("acodec") not in (None, "none")
        ]
        if height:
            capped = [f for f in prog if (f.get("height") or 0) <= height]
            prog = capped or prog
        prog.sort(key=lambda f: f.get("height") or 0, reverse=True)
        chosen = prog[0] if prog else None
        if chosen is None:
            vids = [f for f in formats if f.get("vcodec") not in (None, "none")]
            if height:
                vids = [f for f in vids if (f.get("height") or 0) <= height] or vids
            vids.sort(key=lambda f: f.get("height") or 0, reverse=True)
            chosen = vids[0] if vids else None

    if not chosen:
        raise HTTPException(status_code=422, detail="没有可供浏览器直接播放的媒体地址")
    if chosen.get("http_headers"):
        http_headers.update(chosen["http_headers"])
    ext = (chosen.get("ext") or ("m4a" if audio else "mp4")).lower()
    safe_title = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in title)[:60].strip(" ._") or "youtube"
    return {
        "media_url": chosen["url"],
        "headers": http_headers,
        "filename": f"{safe_title}.{ext}",
        "ext": ext,
    }


def _format_selector(quality: str, audio_format: Optional[str] = None) -> str:
    """Prefer single-file progressive MP4.

    This environment often has no ffmpeg, and googlevideo CDN URLs from
    extract_info frequently 403 when re-fetched by httpx. yt-dlp's own
    downloader with progressive format ``18`` is the reliable path.
    """
    if audio_format:
        return f"bestaudio[ext={audio_format}]/bestaudio/best"
    height = None
    if quality and quality.endswith("p") and quality[:-1].isdigit():
        height = quality[:-1]
    if height:
        # Single-file only — do not request bestvideo+bestaudio (needs ffmpeg).
        return (
            f"best[height<={height}][ext=mp4][vcodec!=none][acodec!=none]/"
            f"best[height<={height}][vcodec!=none][acodec!=none]/"
            f"18/best[ext=mp4]/best"
        )
    return "18/best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best"


def download_to_file(url: str, dest: str, quality: str, audio_format: Optional[str] = None) -> str:
    last_err: Optional[Exception] = None
    fmt = _format_selector(quality, audio_format)
    # android alone is the most reliable for progressive format 18.
    client_tries = (("android",),) + _YOUTUBE_CLIENT_TRIES + (None,)
    for clients in client_tries:
        for cookie_extra in _cookie_extras():
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "outtmpl": dest,
                "merge_output_format": "mp4",
                "noplaylist": True,
                "cachedir": False,
                "format": fmt,
                # Never abort just because merge is unavailable; selector avoids merge.
                "prefer_ffmpeg": False,
            }
            if clients:
                opts["extractor_args"] = {"youtube": {"player_client": list(clients)}}
            opts.update(cookie_extra)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                return dest
            except Exception as e:
                last_err = e
                continue
    raise HTTPException(
        status_code=422,
        detail=f"下载失败：{str(last_err or '未知错误').split(chr(10))[0][:200]}",
    )
