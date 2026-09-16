from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse
import re

import httpx

_HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def browser_headers(url: str, extra: Optional[dict] = None) -> dict:
    host = (urlparse(url).hostname or "").lower()
    referer = "https://www.bilibili.com/"
    if "douyin" in host or "iesdouyin" in host:
        referer = "https://www.douyin.com/"
    elif "youtube" in host or "youtu.be" in host:
        referer = "https://www.youtube.com/"
    elif "x.com" in host or "twitter.com" in host or "twimg.com" in host or host == "t.co":
        referer = "https://x.com/"
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Origin": referer.rstrip("/"),
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if extra:
        headers.update(extra)
    return headers


def get_json(url: str, headers: Optional[dict] = None, timeout: float = 25.0) -> Any:
    h = browser_headers(url, headers)
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=h) as client:
        res = client.get(url)
        res.raise_for_status()
        return res.json()


def get_text(url: str, headers: Optional[dict] = None, timeout: float = 25.0) -> tuple[str, str]:
    h = browser_headers(url, headers)
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=h) as client:
        res = client.get(url)
        res.raise_for_status()
        return str(res.url), res.text


def format_count(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def format_duration(seconds: Any) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return "00:00"
    m, sec = divmod(max(s, 0), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def extract_http_url(raw: str) -> str:
    """Allow Douyin-style share paste: 文案 + https://v.douyin.com/xxx/"""
    text = (raw or "").strip()
    if not text:
        return text
    if text.startswith("http://") or text.startswith("https://"):
        return text.split()[0].rstrip(".,，。)/")
    found = _HTTP_URL_RE.findall(text)
    if found:
        return found[0].rstrip(".,，。)/")
    return text
