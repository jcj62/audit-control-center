from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable
from urllib import error, request

from .config import settings


ASSET_KEYWORDS = [
    "db",
    "vdb",
    "pldb",
    "pdb",
    "panel",
    "control panel",
    "mccb",
    "ups",
    "transformer",
    "feeder",
    "dg",
    "incomer",
    "ldb",
    "battery",
    "socket",
]

FAULT_HINTS = [
    "fault",
    "open",
    "missing",
    "damage",
    "burn",
    "leak",
    "trip",
    "broken",
    "loose",
    "improper",
    "no ",
]


@dataclass
class ParsedFault:
    building: str
    location: str
    asset: str
    fault_type: str


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _detect_asset(parts: Iterable[str]) -> tuple[str, int | None]:
    for index, part in enumerate(parts):
        lowered = part.lower()
        if any(keyword in lowered for keyword in ASSET_KEYWORDS):
            return part.strip(), index
    return "unknown", None


def _extract_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _call_ollama(message: str, parsed: ParsedFault) -> ParsedFault | None:
    if not settings.ollama_url:
        return None

    prompt = f"""
Extract electrical audit data from this WhatsApp message.

Message: {message}

Current parse:
building={parsed.building}
location={parsed.location}
asset={parsed.asset}
fault_type={parsed.fault_type}

Return strict JSON:
{{"building":"","location":"","asset":"","fault_type":""}}
""".strip()

    payload = json.dumps(
        {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "temperature": 0,
        }
    ).encode("utf-8")

    req = request.Request(
        settings.ollama_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    extracted = _extract_json(raw.get("response", ""))
    if not extracted:
        return None

    return ParsedFault(
        building=normalize_text(extracted.get("building") or parsed.building or "unknown"),
        location=normalize_text(extracted.get("location") or parsed.location or "unknown"),
        asset=normalize_text(extracted.get("asset") or parsed.asset or "unknown"),
        fault_type=normalize_text(extracted.get("fault_type") or parsed.fault_type or "general fault"),
    )


def parse_message(message: str, override_fault: str | None = None, override_asset: str | None = None) -> list[ParsedFault]:
    raw_message = normalize_text(message)

    if not raw_message:
        return [
            ParsedFault(
                building="unknown",
                location="unknown",
                asset=override_asset or "unknown",
                fault_type=override_fault or "general fault",
            )
        ]

    parts = [part.strip() for part in re.split(r"[,\n|]+", raw_message) if part.strip()]

    building = parts[0] if parts else "unknown"
    location = parts[1] if len(parts) > 1 else raw_message[:100]
    asset, asset_index = _detect_asset(parts)

    fault_segments: list[str] = []
    if asset_index is not None and asset_index + 1 < len(parts):
        fault_segments = parts[asset_index + 1 :]
    elif len(parts) > 2:
        fault_segments = parts[2:]
    elif any(hint in raw_message.lower() for hint in FAULT_HINTS):
        fault_segments = [raw_message]

    if not fault_segments:
        fault_segments = ["general fault"]

    parsed_faults: list[ParsedFault] = []
    for fault_text in fault_segments:
        parsed = ParsedFault(
            building=building or "unknown",
            location=location or "unknown",
            asset=override_asset or asset or "unknown",
            fault_type=override_fault or fault_text or "general fault",
        )

        low_quality = parsed.building == "unknown" or parsed.fault_type == "general fault"
        recovered = _call_ollama(raw_message, parsed) if low_quality else None
        parsed_faults.append(recovered or parsed)

    return parsed_faults
