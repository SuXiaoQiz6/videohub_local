from __future__ import annotations

from pathlib import Path
from time import time
from typing import Optional
from urllib.parse import quote, urlparse
import re
import tempfile

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from backend import bilibili, douyin, twitter
from backend.httputil import extract_http_url
from backend.ytdlp_engine import build_result, download_to_file, extract, pick_media as ytdlp_pick

app = FastAPI(title="VideoHub API", version="0.2.0")

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
    "x.com",
    "twitter.com",
    "t.co",
)

UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\r\n]+')
_PICK_CACHE: dict = {}
_PICK_TTL = 180.0
# YouTube googlevideo CDN URLs often 403 when proxied; cache yt-dlp local files instead.
_YT_FILE_CACHE: dict = {}
_YT_FILE_TTL = 600.0


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
    if "douyin" in host or "iesdouyin" in host:
        return "抖音"
    if "youtube" in host or "youtu.be" in host:
        return "YouTube"
    if "x.com" in host or "twitter.com" in host or host == "t.co" or host.endswith(".t.co"):
        return "X"
    return "Unknown"


def _clean_name(name: str) -> str:
    name = UNSAFE_NAME.sub("_", (name or "video").strip()) or "video"
    return name.strip(" ._")[:80] or "video"


def _disposition_headers(filename: str, inline: bool) -> dict:
    ascii_name = _clean_name(filename).encode("ascii", "ignore").decode().strip(" ._") or "video.mp4"
    if not ascii_name.lower().endswith((".mp4", ".m4a", ".mp3", ".webm", ".mkv")):
        ascii_name = f"{ascii_name}.mp4"
    quoted = quote(_clean_name(filename))
    kind = "inline" if inline else "attachment"
    return {
        "Content-Disposition": f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
    }


def _parse_url(url: str) -> dict:
    url = extract_http_url(url)
    if not url:
        raise HTTPException(status_code=400, detail="请输入想要解析的音视频资源链接")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="URL 格式错误。请输入 B 站、抖音、YouTube 或 X 的音视频页面链接。",
        )
    if not _host_ok(url):
        raise HTTPException(
            status_code=400,
            detail="暂不支持该平台。MVP 仅支持 B 站、抖音、YouTube、X。",
        )
    if bilibili.is_bilibili(url):
        return bilibili.parse(url)
    if douyin.is_douyin(url):
        result = douyin.parse(url)
        result.pop("_play", None)
        result.pop("_aweme", None)
        result.pop("_aweme_id", None)
        return result
    if twitter.is_twitter(url):
        result = twitter.parse(url)
        result.pop("_play", None)
        result.pop("_variants", None)
        return result
    info = extract(url)
    return build_result(url, info, _platform_name(url))


@app.get("/api/health")
def health():
    return {"ok": True, "service": "videohub", "mode": "proxy-download"}


@app.post("/api/parse")
def parse(body: ParseRequest):
    try:
        return {"ok": True, "result": _parse_url(body.url)}
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=422, detail=f"解析失败：网络错误 {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析异常：{type(e).__name__}") from e


@app.post("/api/resolve-item")
def resolve_item(body: ParseRequest):
    try:
        result = _parse_url(body.url)
        if result.get("kind") == "collection":
            item = next(
                (it for it in result["items"] if it.get("webpageUrl") == body.url.strip()),
                result["items"][0],
            )
            return {
                "ok": True,
                "item": item,
                "qualities": result.get("qualities") or ["best"],
                "defaultQuality": result.get("defaultQuality") or "best",
            }
        return {
            "ok": True,
            "item": result["item"],
            "qualities": result.get("qualities") or result.get("formats") or ["best"],
            "defaultQuality": result.get("defaultQuality") or result.get("defaultFormat") or "best",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"条目解析失败：{e}") from e


def _pick_media(url: str, quality: str, audio: bool = False, audio_format: Optional[str] = None) -> dict:
    key = (url, quality, bool(audio), audio_format or "")
    hit = _PICK_CACHE.get(key)
    now = time()
    if hit and now - hit[0] < _PICK_TTL:
        return hit[1]
    if bilibili.is_bilibili(url):
        picked = bilibili.pick_media(url, quality)
    elif douyin.is_douyin(url):
        picked = douyin.pick_media(url, quality)
    elif twitter.is_twitter(url):
        picked = twitter.pick_media(url, quality)
    else:
        picked = ytdlp_pick(url, quality, audio=audio, audio_format=audio_format)
    _PICK_CACHE[key] = (now, picked)
    return picked


def _stream_remote(
    media_url: str,
    headers: dict,
    filename: str,
    inline: bool = False,
    range_header: Optional[str] = None,
    method: str = "GET",
):
    req_headers = dict(headers)
    if range_header:
        req_headers["Range"] = range_header
    client = httpx.Client(follow_redirects=True, timeout=None, headers=req_headers)
    req = client.build_request(method, media_url)
    res = client.send(req, stream=True)
    if res.status_code >= 400:
        res.close()
        client.close()
        raise HTTPException(status_code=422, detail=f"取流失败 HTTP {res.status_code}")

    def iter_close():
        try:
            for chunk in res.iter_bytes(64 * 1024):
                if chunk:
                    yield chunk
        finally:
            res.close()
            client.close()

    media_type = res.headers.get("content-type") or "video/mp4"
    if inline:
        low = (media_type or "").split(";")[0].strip().lower()
        if low in ("", "application/octet-stream", "binary/octet-stream", "text/plain"):
            media_type = "audio/mp4" if filename.lower().endswith((".m4a", ".mp3", ".aac")) else "video/mp4"
        out_headers = {
            "Accept-Ranges": res.headers.get("accept-ranges") or "bytes",
            "Cache-Control": "no-store",
        }
    else:
        out_headers = _disposition_headers(filename, inline=False)
        out_headers["Accept-Ranges"] = res.headers.get("accept-ranges") or "bytes"
    if res.headers.get("content-length"):
        out_headers["Content-Length"] = res.headers["content-length"]
    if res.headers.get("content-range"):
        out_headers["Content-Range"] = res.headers["content-range"]
    if method == "HEAD":
        res.close()
        client.close()
        return Response(status_code=res.status_code, headers=out_headers, media_type=media_type)
    return StreamingResponse(
        iter_close(),
        status_code=res.status_code,
        media_type=media_type,
        headers=out_headers,
    )


def _youtube_local_file(url: str, quality: str, audio: bool, audio_format: Optional[str]) -> Path:
    """Download via yt-dlp to a cached temp file (CDN proxy is unreliable for YouTube)."""
    key = (url, quality, bool(audio), audio_format or "")
    now = time()
    hit = _YT_FILE_CACHE.get(key)
    if hit and now - hit[0] < _YT_FILE_TTL and hit[1].is_file():
        return hit[1]
    tmpdir = Path(tempfile.mkdtemp(prefix="videohub-yt-"))
    dest = str(tmpdir / "%(id)s.%(ext)s")
    download_to_file(url, dest, quality, audio_format if audio else None)
    files = [p for p in tmpdir.iterdir() if p.is_file()]
    if not files:
        raise HTTPException(status_code=422, detail="下载完成但未找到文件")
    fpath = max(files, key=lambda p: p.stat().st_size)
    _YT_FILE_CACHE[key] = (now, fpath)
    return fpath


def _file_media_response(fpath: Path, inline: bool, request: Request):
    name = _clean_name(fpath.name)
    media_type = "video/mp4"
    low = fpath.suffix.lower()
    if low in (".m4a", ".mp3", ".aac", ".opus", ".webm"):
        media_type = "audio/mp4" if low != ".webm" else "audio/webm"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if not inline:
        headers.update(_disposition_headers(name, inline=False))
        media_type = "application/octet-stream"
        return FileResponse(
            path=str(fpath),
            filename=name,
            media_type=media_type,
            headers=headers,
        )
    # Preview: no Content-Disposition, so the browser <video> plays inline.
    return FileResponse(
        path=str(fpath),
        media_type=media_type,
        headers=headers,
    )


def _media_response(
    url: str,
    quality: str,
    audio: bool,
    audio_format: Optional[str],
    inline: bool,
    request: Request,
):
    url = url.strip()
    if not _host_ok(url):
        raise HTTPException(status_code=400, detail="不支持的下载链接")
    range_header = request.headers.get("range")
    method = request.method.upper() if request.method.upper() in ("GET", "HEAD") else "GET"
    host = (urlparse(url).hostname or "").lower()
    youtube = "youtube.com" in host or "youtu.be" in host

    # YouTube: skip googlevideo CDN proxy (often HTTP 403). Use yt-dlp local file
    # for both preview (/api/stream) and download — same as the old download-only fallback.
    if youtube:
        # Preview should stay light: use lowest practical progressive ladder.
        q = quality
        if inline and not audio:
            q = "360p"
        fpath = _youtube_local_file(url, q, audio, audio_format)
        return _file_media_response(fpath, inline=inline, request=request)

    try:
        picked = _pick_media(url, quality, audio=audio, audio_format=audio_format)
        return _stream_remote(
            picked["media_url"],
            picked["headers"],
            picked["filename"],
            inline=inline,
            range_header=range_header,
            method=method,
        )
    except HTTPException:
        raise


@app.api_route("/api/stream", methods=["GET", "HEAD"])
def stream(
    request: Request,
    url: str,
    quality: str = "best",
    format: Optional[str] = None,
    audio: bool = False,
):
    return _media_response(url, quality, audio, format, inline=True, request=request)


@app.api_route("/api/download", methods=["GET", "HEAD"])
def download(
    request: Request,
    url: str,
    quality: str = "best",
    format: Optional[str] = None,
    audio: bool = False,
):
    return _media_response(url, quality, audio, format, inline=False, request=request)
