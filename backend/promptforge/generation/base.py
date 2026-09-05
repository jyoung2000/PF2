"""Generation provider interface (8.1) — one adapter file per provider so new
providers are a single file + one registry line."""
from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from .. import settings_store


class ProviderError(Exception):
    def __init__(self, message: str, step: str = "unknown"):
        super().__init__(message)
        self.step = step


class GenerationProvider:
    name = "base"
    label = "Base"
    key_setting = ""          # settings key holding the API key
    key_url = ""              # where the user creates a key

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def _client(self, key: str, extra_headers: dict | None = None) -> httpx.Client:
        kw: dict = {"timeout": 60, "headers": self.auth_headers(key)}
        if extra_headers:
            kw["headers"].update(extra_headers)
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.Client(**kw)

    def auth_headers(self, key: str) -> dict:
        raise NotImplementedError

    def get_key(self, s: Session) -> str:
        return settings_store.get(s, self.key_setting) or ""

    def is_configured(self, s: Session) -> bool:
        return bool(self.get_key(s))

    # -- contract ------------------------------------------------------------
    def test_connection(self, key: str) -> dict:
        """{ok, detail}. Must NEVER trigger a paid generation (D10)."""
        raise NotImplementedError

    def submit(self, key: str, model_id: str, prompt: str,
               negative: str | None, params: dict, kind: str) -> str:
        """Start a generation → provider job reference (string)."""
        raise NotImplementedError

    def poll(self, key: str, model_id: str, job_ref: str) -> dict:
        """→ {status: queued|running|succeeded|failed, output_url?, error?}"""
        raise NotImplementedError


def image_inputs(params: dict) -> dict:
    """Film Studio / Studio image inputs carried in params (never sent as-is):
    {"image": path|url, "end_image": path|url, "references": [path|url…],
    "strength": float}. Adapters map them onto their own field names via
    `params["_input_map"]` (from the pricing catalog `modes[...].inputs`)."""
    inputs = params.get("_inputs") if isinstance(params.get("_inputs"), dict) else {}
    return {k: v for k, v in inputs.items() if v not in (None, "", [])}


def input_map(params: dict, defaults: dict) -> dict:
    m = dict(defaults)
    given = params.get("_input_map") if isinstance(params.get("_input_map"), dict) else {}
    m.update({k: v for k, v in given.items() if isinstance(v, (str, bool))})
    return m


def data_uri(path_or_url: str) -> str:
    """Local file → base64 data URI (providers accept these for image inputs);
    http(s)/data URLs pass through untouched."""
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    import base64
    import mimetypes
    from pathlib import Path
    p = Path(path_or_url)
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def apply_image_inputs(payload: dict, params: dict, defaults: dict,
                       convert=data_uri) -> dict:
    """Place image/end_image/references/strength into the payload using the
    provider's field names. `list: True` in the map wraps single images in a
    list (multi-image edit endpoints)."""
    inputs = image_inputs(params)
    if not inputs:
        return payload
    m = input_map(params, defaults)
    as_list = bool(m.get("list"))
    for key in ("image", "end_image"):
        if inputs.get(key) and m.get(key):
            val = convert(str(inputs[key]))
            field = m[key]
            if as_list and key == "image":
                payload.setdefault(field, [])
                if isinstance(payload[field], list):
                    payload[field].append(val)
            else:
                payload[field] = val
    refs = inputs.get("references") or []
    if refs and m.get("references"):
        field = m["references"]
        vals = [convert(str(r)) for r in refs[:6]]
        if isinstance(payload.get(field), list):
            payload[field] += vals
        else:
            payload[field] = vals if (as_list or len(vals) > 1) else vals[0]
    if inputs.get("strength") is not None and m.get("strength"):
        try:
            payload[m["strength"]] = float(inputs["strength"])
        except (TypeError, ValueError):
            pass
    return payload


def build_common_payload(prompt: str, negative: str | None, params: dict,
                         kind: str) -> dict:
    """Provider-neutral fields; adapters reshape as needed."""
    payload: dict = {"prompt": prompt}
    if negative:
        payload["negative_prompt"] = negative
    if kind == "video":
        duration = params.get("duration_s") or 5
        payload["duration"] = int(duration)
    else:
        size = str(params.get("size") or "1024x1024")
        try:
            w, h = (int(x) for x in size.lower().split("x"))
        except ValueError:
            w = h = 1024
        payload["width"], payload["height"] = w, h
    if params.get("seed") not in (None, ""):
        payload["seed"] = params["seed"]
    return payload
