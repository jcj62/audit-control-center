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

UNKNOWN_MARKERS = {"", "unknown", "n/a", "na", "nil", "none", "-"}

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


def is_unknown(value: str | None) -> bool:
    return normalize_text(value or "").lower() in UNKNOWN_MARKERS


def _clean_field(value: str | None, fallback: str) -> str:
    cleaned = normalize_text(value or "")
    cleaned = cleaned.strip(" ,;:-")
    return cleaned or fallback


def _normalize_fault_type(value: str | None, message: str) -> str:
    cleaned = _clean_field(value, "")
    lowered = cleaned.lower()

    aliases = {
        "gen fault": "general fault",
        "general": "general fault",
        "fault": "general fault",
        "trip": "tripping fault",
        "open": "open fault",
    }

    if lowered in aliases:
        return aliases[lowered]

    if not cleaned or cleaned.lower() == "image-only submission":
        if normalize_text(message):
            return cleaned or "general fault"
        return "general fault"

    return cleaned


def _normalize_asset(value: str | None) -> str:
    cleaned = _clean_field(value, "unknown")
    lowered = cleaned.lower()

    aliases = {
        "db board": "DB",
        "distribution board": "DB",
        "lt panel": "LT Panel",
        "ht panel": "HT Panel",
        "ups panel": "UPS",
    }

    return aliases.get(lowered, cleaned)


def _fallback_location(message: str) -> str:
    raw = normalize_text(message)
    return raw[:120] if raw else "unknown"


def _detect_asset(parts: Iterable[str]) -> tuple[str, int | None]:
    for index, part in enumerate(parts):
        lowered = part.lower()
        if any(keyword in lowered for keyword in ASSET_KEYWORDS):
            return part.strip(), index
    return "unknown", None


def _base_parse_message(message: str, override_fault: str | None = None, override_asset: str | None = None) -> list[ParsedFault]:
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
    location = parts[1] if len(parts) > 1 else _fallback_location(raw_message)
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
        parsed_faults.append(
            ParsedFault(
                building=building or "unknown",
                location=location or "unknown",
                asset=override_asset or asset or "unknown",
                fault_type=override_fault or fault_text or "general fault",
            )
        )

    return parsed_faults


def _extract_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _call_ollama(message: str, parsed: ParsedFault, prompt_mode: str) -> ParsedFault | None:
    if not settings.ollama_url:
        return None

    if prompt_mode == "validator":
        prompt = f"""
Validate and improve this electrical audit parse from a WhatsApp message.

Message: {message}

Candidate parse:
building={parsed.building}
location={parsed.location}
asset={parsed.asset}
fault_type={parsed.fault_type}

Fix only if clearly wrong or incomplete. Keep the original meaning.
Return strict JSON:
{{"building":"","location":"","asset":"","fault_type":""}}
""".strip()
    else:
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


def _needs_llm_correction(parsed: ParsedFault, message: str) -> bool:
    normalized_message = normalize_text(message)
    return any(
        [
            is_unknown(parsed.building),
            is_unknown(parsed.location),
            is_unknown(parsed.asset),
            parsed.fault_type.lower() == "general fault",
            parsed.location == normalized_message,
        ]
    )


def _validator_pass(message: str, parsed: ParsedFault, override_fault: str | None = None, override_asset: str | None = None) -> ParsedFault:
    normalized_message = normalize_text(message)

    building = _clean_field(parsed.building, "unknown")
    location = _clean_field(parsed.location, _fallback_location(normalized_message))
    asset = _normalize_asset(override_asset or parsed.asset)
    fault_type = _normalize_fault_type(override_fault or parsed.fault_type, normalized_message)

    if is_unknown(location):
        location = _fallback_location(normalized_message)

    if is_unknown(building) and location and location != "unknown":
        building = location

    if is_unknown(asset) and any(keyword in location.lower() for keyword in ASSET_KEYWORDS):
        asset = location

    if not normalized_message:
        location = "Image-only submission"
        if is_unknown(building):
            building = "Image-only submission"
        fault_type = override_fault or fault_type or "general fault"

    return ParsedFault(
        building=building,
        location=location,
        asset=asset,
        fault_type=fault_type or "general fault",
    )


def parse_message(message: str, override_fault: str | None = None, override_asset: str | None = None) -> list[ParsedFault]:
    raw_message = normalize_text(message)
    base_faults = _base_parse_message(raw_message, override_fault, override_asset)
    parsed_faults: list[ParsedFault] = []
    for parsed in base_faults:
        corrected = _call_ollama(raw_message, parsed, "correction") if _needs_llm_correction(parsed, raw_message) else None
        candidate = corrected or parsed
        validated = _validator_pass(raw_message, candidate, override_fault, override_asset)
        llm_validated = _call_ollama(raw_message, validated, "validator") if settings.ollama_url else None
        final_fault = _validator_pass(raw_message, llm_validated or validated, override_fault, override_asset)
        parsed_faults.append(final_fault)

    return parsed_faults
