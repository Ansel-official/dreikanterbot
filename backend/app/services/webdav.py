"""最小 WebDAV 客户端：个人云端同步（Nextcloud / 坚果云 / 群晖等）。"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from urllib.parse import quote, urljoin, urlparse

import httpx

from ..config import settings

PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/><d:resourcetype/></d:prop>
</d:propfind>"""


class WebDAVError(Exception):
    pass


def validate_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("WebDAV 地址必须是 http(s) URL")
    return value


def _auth(username: str, password: str) -> httpx.BasicAuth:
    return httpx.BasicAuth(username, password)


def _url(base: str, *segments: str) -> str:
    tail = "/".join(quote(seg.strip("/"), safe="") for seg in segments if seg and seg.strip("/"))
    return f"{base.rstrip('/')}/{tail}" if tail else base.rstrip("/")


async def ensure_collection(client: httpx.AsyncClient, url: str) -> None:
    response = await client.request("MKCOL", url)
    if response.status_code not in {201, 204, 301, 302, 405, 409}:
        raise WebDAVError(f"创建云端目录失败（HTTP {response.status_code}）")


async def ensure_path(client: httpx.AsyncClient, base: str, remote_path: str) -> str:
    current = base.rstrip("/")
    for segment in [part for part in remote_path.split("/") if part.strip()]:
        current = _url(current, segment)
        await ensure_collection(client, current)
    return current


async def put_file(client: httpx.AsyncClient, url: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    response = await client.put(url, content=data, headers={"Content-Type": content_type})
    if response.status_code not in {200, 201, 204}:
        raise WebDAVError(f"上传云端失败（HTTP {response.status_code}）")


async def get_file(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    async with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise WebDAVError(f"下载云端文件失败（HTTP {response.status_code}）")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise WebDAVError("云端文件超过大小限制")
            chunks.append(chunk)
        return b"".join(chunks)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


async def list_files(client: httpx.AsyncClient, url: str) -> list[dict]:
    response = await client.request(
        "PROPFIND",
        url,
        content=PROPFIND_BODY.encode("utf-8"),
        headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
    )
    if response.status_code not in {200, 207}:
        raise WebDAVError(f"读取云端目录失败（HTTP {response.status_code}）")
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise WebDAVError("云端返回的不是有效 WebDAV XML") from exc
    items: list[dict] = []
    base_for_join = url if url.endswith("/") else url + "/"
    for node in root:
        href = ""
        size = 0
        is_dir = False
        for child in node:
            name = _local_name(child.tag)
            if name == "href":
                href = (child.text or "").strip()
            elif name == "getcontentlength":
                try:
                    size = int(child.text or 0)
                except ValueError:
                    size = 0
            elif name == "resourcetype":
                for sub in child:
                    if _local_name(sub.tag) == "collection":
                        is_dir = True
        if href:
            items.append(
                {
                    "href": urljoin(base_for_join, href),
                    "size": size,
                    "is_dir": is_dir,
                    "name": href.rstrip("/").rsplit("/", 1)[-1],
                }
            )
    return items


def client_for(base_url: str, username: str, password: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=_auth(username, password),
        timeout=httpx.Timeout(settings.webdav_timeout_seconds, connect=15.0),
        follow_redirects=True,
        headers={"User-Agent": "Dreikanterbot/3.0"},
    )


def basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"
