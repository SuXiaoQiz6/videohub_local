"""Bilibili parser via official JSON APIs (same idea as 鱼皮：平台专用解析，不让用户导 Cookie)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException

from backend.httputil import browser_headers, format_count, format_duration, get_json

BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")

# 清晰度 qn：未登录通常最高 720p（64）
QN_BY_LABEL = {
    "360p": 16,
    "480p": 32,
    "720p": 64,
    "1080p": 80,
    "1080p+": 112,
    "4k": 120,
}
LABEL_BY_QN = {v: k for k, v in QN_BY_LABEL.items()}
LABEL_BY_QN[74] = "720p60"
LABEL_BY_QN[116] = "1080p60"


def is_bilibili(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return "bilibili.com" in host or host.endswith("b23.tv") or host == "b23.tv"


def _resolve_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "b23.tv" or host.endswith(".b23.tv"):
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=browser_headers(url)) as client:
            res = client.get(url)
            res.raise_for_status()
            return str(res.url)
    return url


def _bvid_from_url(url: str) -> str:
    m = BV_RE.search(url)
    if m:
        return m.group(0)
    raise HTTPException(status_code=422, detail="无法从链接中识别 B 站 BV 号")


def _page_index(url: str, page_count: int) -> int:
    qs = parse_qs(urlparse(url).query)
    if "p" in qs:
        try:
            p = int(qs["p"][0])
            if 1 <= p <= page_count:
                return p
        except ValueError:
            pass
    return 1


def _view(bvid: str) -> dict:
    data = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if data.get("code") != 0 or not data.get("data"):
        raise HTTPException(
            status_code=422,
            detail=f"B 站解析失败：{data.get('message') or data.get('code')}",
        )
    return data["data"]


def _pagelist(bvid: str) -> list:
    """Full 分P list — view.pages may truncate; pagelist is the authoritative source."""
    data = get_json(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}")
    if data.get("code") != 0:
        raise HTTPException(
            status_code=422,
            detail=f"B 站分 P 列表失败：{data.get('message') or data.get('code')}",
        )
    return list(data.get("data") or [])


def _pages_for(bvid: str, view: dict) -> list:
    pages = _pagelist(bvid)
    if pages:
        return pages
    return view.get("pages") or [
        {
            "cid": view.get("cid"),
            "page": 1,
            "part": view.get("title"),
            "duration": view.get("duration"),
        }
    ]


def _playurl(bvid: str, cid: int, qn: int = 80, fnval: int = 1) -> dict:
    url = (
        "https://api.bilibili.com/x/player/playurl"
        f"?bvid={bvid}&cid={cid}&qn={qn}&fnval={fnval}&fourk=1"
    )
    data = get_json(url)
    if data.get("code") != 0 or not data.get("data"):
        raise HTTPException(
            status_code=422,
            detail=f"B 站取流失败：{data.get('message') or data.get('code')}",
        )
    return data["data"]


def _collect_qualities(play: dict) -> list[str]:
    seen: list[str] = []
    accept = play.get("accept_quality") or []
    for qn in accept:
        label = LABEL_BY_QN.get(int(qn))
        if label and label not in seen:
            seen.append(label)
    if not seen:
        qn = play.get("quality")
        if qn:
            seen.append(LABEL_BY_QN.get(int(qn), f"{qn}"))
    if not seen:
        seen = ["720p", "480p", "360p"]
    # 高 → 低
    def key(q: str) -> int:
        try:
            return int(q.replace("p+", "1").replace("p60", "").replace("k", "000").rstrip("p") or "0")
        except ValueError:
            return 0

    seen.sort(key=key, reverse=True)
    return seen


def _item_from_view(view: dict, page: dict, index: int, bvid: str) -> dict:
    cid = page.get("cid") or view.get("cid")
    p = page.get("page") or index
    title = page.get("part") or view.get("title") or f"P{p}"
    if view.get("pages") and len(view["pages"]) > 1:
        title = f"P{p} · {title}"
    else:
        title = view.get("title") or title
    owner = view.get("owner") or {}
    stat = view.get("stat") or {}
    return {
        "id": str(cid),
        "index": index,
        "title": title,
        "author": owner.get("name") or "-",
        "views": format_count(stat.get("view")),
        "likes": format_count(stat.get("like")),
        "duration": format_duration(page.get("duration") or view.get("duration")),
        "description": (view.get("desc") or "暂无简介")[:240],
        "thumbnail": page.get("first_frame") or view.get("pic"),
        "downloadUrl": "",
        "webpageUrl": f"https://www.bilibili.com/video/{bvid}?p={p}",
        "bvid": bvid,
        "cid": cid,
    }


def parse(url: str) -> dict:
    resolved = _resolve_url(url)
    bvid = _bvid_from_url(resolved)
    view = _view(bvid)
    pages = _pages_for(bvid, view)
    items = [_item_from_view(view, pg, i, bvid) for i, pg in enumerate(pages, start=1)]
    current_p = _page_index(resolved, len(items))
    matched = items[current_p - 1] if items else None
    if not matched:
        raise HTTPException(status_code=422, detail="合集为空或无法读取分 P")
    try:
        play = _playurl(bvid, int(matched["cid"]), qn=80, fnval=1)
        qualities = _collect_qualities(play)
    except HTTPException:
        qualities = ["720p", "480p", "360p"]
        play = {}
    default = qualities[0] if qualities else "480p"

    if len(items) > 1:
        return {
            "kind": "collection",
            "platform": "Bilibili",
            "collectionName": view.get("title") or "合集",
            "collectionCount": len(items),
            "parsedId": matched["id"],
            "qualities": qualities,
            "defaultQuality": default,
            "items": items,
            "sourceUrl": resolved,
        }
    return {
        "kind": "video",
        "platform": "Bilibili",
        "qualities": qualities,
        "defaultQuality": default,
        "item": matched,
        "sourceUrl": resolved,
    }


def pick_media(url: str, quality: str) -> dict:
    """Return a progressive mp4 URL + headers for proxy download."""
    resolved = _resolve_url(url)
    bvid = _bvid_from_url(resolved)
    view = _view(bvid)
    pages = _pages_for(bvid, view)
    p = _page_index(resolved, len(pages))
    page = pages[p - 1]
    cid = int(page.get("cid") or view.get("cid"))
    qn = QN_BY_LABEL.get(quality, 80)
    play = _playurl(bvid, cid, qn=qn, fnval=1)
    durl = play.get("durl") or []
    if not durl or not durl[0].get("url"):
        raise HTTPException(status_code=422, detail="该清晰度没有可直接下载的 MP4，请换一档清晰度")
    title = view.get("title") or bvid
    if len(pages) > 1:
        title = f"{title}-P{p}"
    safe = f"{bvid}-P{p}.mp4" if len(pages) > 1 else f"{bvid}.mp4"
    return {
        "media_url": durl[0]["url"],
        "headers": browser_headers(resolved),
        "filename": safe,
        "ext": "mp4",
    }
