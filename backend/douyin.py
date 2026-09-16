"""Douyin parser.

Primary path (current Douyin web):
  short link → aweme_id → bootstrap __ac_nonce/__ac_signature →
  jingxuan?modal_id= SSR RENDER_DATA → CDN playAddr

Fallbacks kept for when SSR layout changes again:
  iesdouyin iteminfo / share _ROUTER_DATA / yt-dlp
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import HTTPException

from backend.httputil import format_count, format_duration

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)

VIDEO_ID_RE = re.compile(
    r"(?:video|note|share/video)/(\d{15,})|(?:modal_id|aweme_id|item_ids)=(\d{15,})",
    re.I,
)
RENDER_DATA_RE = re.compile(
    r'<script[^>]+id="RENDER_DATA"[^>]*>([^<]+)</script>', re.I
)


def is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "douyin.com" in host or "iesdouyin.com" in host


def _pc_headers() -> dict:
    return {
        "User-Agent": PC_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _mobile_headers() -> dict:
    return {
        "User-Agent": MOBILE_UA,
        "Referer": "https://www.iesdouyin.com/",
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _cdn_headers() -> dict:
    return {
        "User-Agent": PC_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _extract_aweme_id(text: str) -> Optional[str]:
    if not text:
        return None
    m = VIDEO_ID_RE.search(text)
    if not m:
        return None
    return m.group(1) or m.group(2)


def _ac_signature(site: str, nonce: str, ua: str, ts: Optional[int] = None) -> str:
    """Port of Douyin web __ac_signature (byted_acrawler.sign)."""
    if ts is None:
        ts = int(time.time())

    def cal1(s: str, iv: int) -> int:
        k = iv
        for ch in s:
            k = ((k ^ ord(ch)) * 65599) & 0xFFFFFFFF
        return k

    def cal3(s: str, iv: int) -> int:
        k = iv
        for ch in s:
            k = (k * 65599 + ord(ch)) & 0xFFFFFFFF
        return k

    def one_chr(code: int) -> str:
        if code < 26:
            return chr(code + 65)
        if code < 52:
            return chr(code + 71)
        if code < 62:
            return chr(code - 4)
        return chr(code - 17)

    def enc(n: int) -> str:
        return "".join(one_chr((n >> i) & 63) for i in range(24, -1, -6))

    a = cal1(site, cal1(str(ts), 0)) % 65521
    b = int("10000000110000" + bin(ts ^ (a * 65521))[2:].zfill(32), 2)
    c = cal1(str(b), 0)
    d = enc(b >> 2)
    e = (b // 4294967296) & 0xFFFFFFFF
    f = enc((b << 28) | (e >> 4))
    g = 582085784 ^ b
    h = enc((e << 26) | (g >> 6))
    i = one_chr(g & 63)
    j = ((cal1(ua, c) % 65521) << 16) | (cal1(nonce, c) % 65521)
    k = enc(j >> 2)
    l = enc((j << 28) | ((524576 ^ b) >> 4))
    m = enc(a)
    body = "_02B4Z6wo00f01" + d + f + h + i + k + l + m
    checksum = hex(cal3(body, 0))[2:][-2:].zfill(2)
    return body + checksum


def _resolve(url: str) -> tuple[str, str]:
    """Follow share short-link. Returns (aweme_id, final_url)."""
    direct = _extract_aweme_id(url)
    if direct and "v.douyin.com" not in (urlparse(url).hostname or ""):
        return direct, url

    final = url
    with httpx.Client(follow_redirects=False, timeout=20.0, headers=_mobile_headers()) as client:
        current = url
        for _ in range(10):
            res = client.get(current)
            loc = res.headers.get("location")
            if loc:
                if loc.startswith("/"):
                    loc = str(httpx.URL(current).join(loc))
                current = loc
                final = loc
                mid = _extract_aweme_id(loc)
                if mid:
                    return mid, loc
                continue
            final = str(res.url) if str(res.url) else current
            mid = _extract_aweme_id(final) or _extract_aweme_id(res.text)
            if mid:
                return mid, final
            break

    with httpx.Client(follow_redirects=True, timeout=20.0, headers=_mobile_headers()) as client:
        res = client.get(url)
        final = str(res.url)
        mid = _extract_aweme_id(final) or _extract_aweme_id(url) or _extract_aweme_id(res.text)
        if mid:
            return mid, final

    raise HTTPException(
        status_code=422,
        detail="无法从抖音链接识别视频 ID。请粘贴 App 里「分享 → 复制链接」的短链（v.douyin.com）。",
    )


def _collect_urls(node) -> list[str]:
    out: list[str] = []
    if isinstance(node, str) and node.startswith("http"):
        out.append(node)
    elif isinstance(node, list):
        for item in node:
            out.extend(_collect_urls(item))
    elif isinstance(node, dict):
        if "urlList" in node:
            out.extend(_collect_urls(node["urlList"]))
        elif "url_list" in node:
            out.extend(_collect_urls(node["url_list"]))
        else:
            for v in node.values():
                out.extend(_collect_urls(v))
    return out


def _find_video_detail(obj) -> Optional[dict]:
    if isinstance(obj, dict):
        vd = obj.get("videoDetail")
        if isinstance(vd, dict) and (vd.get("awemeId") or vd.get("video")):
            return vd
        for v in obj.values():
            found = _find_video_detail(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_video_detail(v)
            if found:
                return found
    return None


def _bootstrap_web_client() -> httpx.Client:
    client = httpx.Client(follow_redirects=True, timeout=30.0, headers=_pc_headers())
    client.get("https://www.douyin.com/")
    nonce = client.cookies.get("__ac_nonce")
    if not nonce:
        client.get("https://www.douyin.com/jingxuan")
        nonce = client.cookies.get("__ac_nonce")
    if not nonce:
        client.close()
        raise HTTPException(status_code=422, detail="抖音风控校验失败：未拿到 __ac_nonce")
    sig = _ac_signature("www.douyin.com", nonce, PC_UA)
    client.cookies.set("__ac_signature", sig, domain=".douyin.com")
    client.cookies.set("__ac_referer", "__ac_blank", domain=".douyin.com")
    return client


def _from_render_data(aweme_id: str) -> Optional[dict]:
    pages = [
        f"https://www.douyin.com/jingxuan?modal_id={aweme_id}",
        f"https://www.douyin.com/discover?modal_id={aweme_id}",
        f"https://www.douyin.com/video/{aweme_id}",
    ]
    try:
        client = _bootstrap_web_client()
    except HTTPException:
        return None
    try:
        html = ""
        for page in pages:
            res = client.get(page)
            html = res.text
            if "RENDER_DATA" in html:
                break
        m = RENDER_DATA_RE.search(html)
        if not m:
            return None
        blob = json.loads(unquote(m.group(1)))
        detail = _find_video_detail(blob)
        if not detail:
            return None
        return _detail_to_aweme(detail, aweme_id)
    except Exception:
        return None
    finally:
        client.close()


def _detail_to_aweme(detail: dict, aweme_id: str) -> dict:
    video = detail.get("video") or {}
    author = detail.get("authorInfo") or detail.get("author") or {}
    stats = detail.get("stats") or detail.get("statistics") or {}
    play_urls = _collect_urls(video.get("playAddr"))
    for br in video.get("bitRateList") or []:
        play_urls.extend(_collect_urls(br.get("playAddr")))
    # Prefer first unique URL; SSR already gives no-watermark CDN links.
    seen = set()
    uniq = []
    for u in play_urls:
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq and video.get("uri"):
        uri = str(video["uri"])
        uniq.append(
            f"https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0"
        )
    cover = _collect_urls(
        video.get("coverUrlList")
        or video.get("originCoverUrlList")
        or video.get("cover")
        or video.get("originCover")
    )
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    # Vertical videos report height > width; "720p" means the short side.
    base_res = min(width, height) if width and height else (height or width)
    qualities = []
    for br in video.get("bitRateList") or []:
        bw = int(br.get("width") or width or 0)
        bh = int(br.get("height") or height or 0)
        res = min(bw, bh) if bw and bh else (bh or bw or base_res)
        label = f"{res}p" if res else "origin"
        if label not in qualities:
            qualities.append(label)
    if not qualities:
        qualities = [f"{base_res}p", "origin"] if base_res else ["origin"]

    return {
        "aweme_id": str(detail.get("awemeId") or aweme_id),
        "desc": detail.get("desc") or detail.get("caption") or detail.get("itemTitle") or "抖音视频",
        "author": {
            "nickname": author.get("nickname") or author.get("nickName") or author.get("uniqueId") or "-"
        },
        "statistics": {
            "play_count": stats.get("playCount") or stats.get("play_count"),
            "digg_count": stats.get("diggCount") or stats.get("digg_count"),
        },
        "video": {
            "duration": video.get("duration") or 0,
            "height": height,
            "play_addr": {"url_list": uniq, "uri": str(video.get("uri") or "")},
            "cover": {"url_list": cover},
        },
        "_play": uniq[0] if uniq else "",
        "_qualities": qualities,
    }


def _from_iteminfo(aweme_id: str) -> Optional[dict]:
    api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={aweme_id}"
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=_mobile_headers()) as client:
            data = client.get(api).json()
    except Exception:
        return None
    items = data.get("item_list") or []
    return items[0] if items else None


def _parse_router_json(html: str) -> Optional[dict]:
    idx = html.find("_ROUTER_DATA")
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    end = None
    for i, ch in enumerate(html[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    try:
        return json.loads(html[start:end])
    except json.JSONDecodeError:
        return None


def _find_aweme(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("videoInfoRes"), dict):
            items = (obj["videoInfoRes"].get("item_list") or [])
            if items and isinstance(items[0], dict):
                return items[0]
        if isinstance(obj.get("video"), dict) and (
            "desc" in obj or "author" in obj or "aweme_id" in obj
        ):
            return obj
        for v in obj.values():
            found = _find_aweme(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_aweme(v)
            if found:
                return found
    return None


def _from_share_html(aweme_id: str, page_url: str) -> Optional[dict]:
    share = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=_mobile_headers()) as client:
            html = client.get(share).text
            if "videoInfoRes" not in html and page_url:
                html = client.get(page_url).text
    except Exception:
        return None
    blob = _parse_router_json(html)
    if not blob:
        return None
    return _find_aweme(blob)


def _video_uri_and_urls(video: dict) -> tuple[str, list[str]]:
    play = video.get("play_addr") or video.get("playAddr") or {}
    uri = str(play.get("uri") or video.get("uri") or "")
    urls = list(play.get("url_list") or play.get("urlList") or [])
    for br in video.get("bit_rate") or video.get("bitRateList") or []:
        pa = br.get("play_addr") or br.get("playAddr") or {}
        urls.extend(pa.get("url_list") or pa.get("urlList") or [])
        if not uri:
            uri = str(pa.get("uri") or "")
    return uri, [u for u in urls if u]


def _no_watermark(uri: str, urls: list[str]) -> str:
    cleaned = []
    for u in urls:
        cleaned.append(u.replace("playwm", "play").replace("/playwm/", "/play/"))
    if uri:
        cleaned.append(
            f"https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0"
        )
        cleaned.append(
            f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0"
        )
    if not cleaned:
        raise HTTPException(status_code=422, detail="抖音未返回可播放地址")
    return cleaned[0]


def _to_item(aweme: dict, webpage: str) -> dict:
    video = aweme.get("video") or {}
    author = aweme.get("author") or {}
    stats = aweme.get("statistics") or {}
    cover = video.get("cover") or video.get("origin_cover") or {}
    thumbs = cover.get("url_list") or cover.get("urlList") or []
    dur = video.get("duration") or aweme.get("duration") or 0
    try:
        dur = float(dur)
        if dur > 1000:
            dur = dur / 1000.0
    except (TypeError, ValueError):
        dur = 0
    return {
        "id": str(aweme.get("aweme_id") or aweme.get("id") or ""),
        "index": 1,
        "title": (aweme.get("desc") or "抖音视频")[:120],
        "author": author.get("nickname") or author.get("unique_id") or "-",
        "views": format_count(stats.get("play_count") or stats.get("playCount")),
        "likes": format_count(stats.get("digg_count") or stats.get("diggCount")),
        "duration": format_duration(dur),
        "description": (aweme.get("desc") or "暂无简介")[:240],
        "thumbnail": thumbs[0] if thumbs else None,
        "downloadUrl": "",
        "webpageUrl": webpage,
    }


def _from_ytdlp(url: str) -> Optional[dict]:
    try:
        import yt_dlp
    except ImportError:
        return None
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "cachedir": False,
        "socket_timeout": 20,
        "http_headers": _pc_headers(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None
    play = info.get("url")
    if not play:
        formats = [f for f in (info.get("formats") or []) if f.get("url")]
        formats.sort(key=lambda f: f.get("height") or 0, reverse=True)
        play = formats[0]["url"] if formats else None
    if not play:
        return None
    return {
        "aweme_id": info.get("id") or "",
        "desc": info.get("title") or "抖音视频",
        "author": {"nickname": info.get("uploader") or "-"},
        "statistics": {"play_count": info.get("view_count"), "digg_count": info.get("like_count")},
        "video": {
            "duration": info.get("duration") or 0,
            "height": info.get("height") or 0,
            "play_addr": {"url_list": [play], "uri": ""},
            "cover": {"url_list": [info.get("thumbnail")] if info.get("thumbnail") else []},
        },
        "_play": play,
    }


def _safe_filename(aweme_id: str, title: str) -> str:
    stem = re.sub(r"[^\w\-]+", "_", (title or "").strip(), flags=re.UNICODE)[:40].strip("._")
    if not stem or not stem.isascii():
        stem = f"douyin-{aweme_id}" if aweme_id else "douyin"
    return f"{stem}.mp4"


def parse(url: str) -> dict:
    aweme_id, final = _resolve(url)
    aweme = _from_render_data(aweme_id)
    if aweme is None:
        aweme = _from_iteminfo(aweme_id)
    if aweme is None:
        aweme = _from_share_html(aweme_id, final)
    if aweme is None:
        aweme = _from_ytdlp(f"https://www.douyin.com/video/{aweme_id}")
    if not aweme:
        raise HTTPException(
            status_code=422,
            detail="抖音解析失败。请用 App 分享短链（v.douyin.com），或稍后再试。",
        )
    video = aweme.get("video") or {}
    play = aweme.get("_play") or _no_watermark(*_video_uri_and_urls(video))
    if not play:
        raise HTTPException(status_code=422, detail="抖音未返回可播放地址")
    item = _to_item(aweme, final if "douyin" in final else f"https://www.douyin.com/video/{aweme_id}")
    item["webpageUrl"] = f"https://www.douyin.com/video/{aweme_id}"
    qualities = aweme.get("_qualities")
    if not qualities:
        h = video.get("height") or 0
        qualities = [f"{h}p", "origin"] if h else ["origin"]
    return {
        "kind": "video",
        "platform": "抖音",
        "qualities": qualities,
        "defaultQuality": qualities[0],
        "item": item,
        "sourceUrl": item["webpageUrl"],
        "_play": play,
        "_aweme_id": aweme_id,
    }


def pick_media(url: str, quality: str) -> dict:
    result = parse(url)
    media = result.get("_play")
    if not media:
        raise HTTPException(status_code=422, detail="抖音没有可下载地址")
    aweme_id = result.get("_aweme_id") or result["item"]["id"]
    title = result["item"]["title"] or "douyin"
    return {
        "media_url": media,
        "headers": _cdn_headers(),
        "filename": _safe_filename(str(aweme_id), title),
        "ext": "mp4",
    }
