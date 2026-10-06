from __future__ import annotations

import json
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    pass


def get_bytes(url: str, timeout: float, user_agent: str, headers: dict | None = None) -> bytes:
    request_headers = {"User-Agent": user_agent, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise HttpError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Request failed for {url}: {exc.reason}") from exc


def get_text(url: str, timeout: float, user_agent: str, headers: dict | None = None) -> str:
    payload = get_bytes(url, timeout, user_agent, headers)
    return payload.decode("utf-8", errors="replace")


def get_json(url: str, timeout: float, user_agent: str, headers: dict | None = None):
    return json.loads(get_text(url, timeout, user_agent, headers))


def post_json(url: str, body: dict, timeout: float, user_agent: str) -> dict:
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise HttpError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"Request failed for {url}: {exc.reason}") from exc
    return json.loads(raw)
