"""Sporttery API client. Returns raw JSON dicts."""

import requests

from src.config import (
    API_FIXED_BONUS,
    API_MATCH_LIST,
    REQUEST_TIMEOUT,
    SPORTTERY_HEADERS,
)


def _get(url: str, params: dict | None = None) -> tuple[dict | None, str | None]:
    """GET request, return (data, error_msg)."""
    try:
        resp = requests.get(
            url,
            params=params,
            headers=SPORTTERY_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            return None, f"API error: {data.get('errorMessage', 'unknown')}"
        return data, None
    except requests.RequestException as e:
        return None, str(e)


def fetch_match_list() -> tuple[dict | None, str | None]:
    """Fetch the 'concern' match list (关注赛事)."""
    return _get(API_MATCH_LIST, params={"method": "concern"})


def fetch_fixed_bonus(match_id: str | int) -> tuple[dict | None, str | None]:
    """Fetch full SP odds for a single match."""
    return _get(API_FIXED_BONUS, params={"clientCode": "3001", "matchId": str(match_id)})
