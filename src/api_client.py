"""Sporttery API client. Returns raw JSON dicts."""

from __future__ import annotations

import time

import requests

from src.config import (
    API_FIXED_BONUS,
    API_MATCH_LIST,
    API_RESULT_LIST,
    REQUEST_TIMEOUT,
    SPORTTERY_HEADERS,
)

# Retry defaults
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubles each retry: 1s, 2s, 4s


def _get(
    url: str,
    params: dict | None = None,
    *,
    max_retries: int = _MAX_RETRIES,
) -> tuple[dict | None, str | None]:
    """GET request with exponential-backoff retry. Return (data, error_msg).

    On transient failures (network / HTTP 5xx / timeout) retries up to
    *max_retries* times with exponential backoff before giving up.
    Non-retryable errors (HTTP 4xx, API-level ``success=false``) fail
    immediately.
    """
    last_err: str | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                params=params,
                headers=SPORTTERY_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            # Retry on 5xx server errors
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < max_retries - 1:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                return None, last_err

            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                return None, f"API error: {data.get('errorMessage', 'unknown')}"
            return data, None

        except requests.ConnectionError as e:
            last_err = f"ConnectionError: {e}"
        except requests.Timeout as e:
            last_err = f"Timeout: {e}"
        except requests.HTTPError as e:
            # 4xx — non-transient, fail immediately
            return None, str(e)
        except requests.RequestException as e:
            return None, str(e)
        except ValueError as e:
            # JSONDecodeError — malformed response body
            return None, f"JSON decode error: {e}"

        if attempt < max_retries - 1:
            time.sleep(_BACKOFF_BASE * (2 ** attempt))

    return None, last_err or "unknown error"


def fetch_match_list() -> tuple[dict | None, str | None]:
    """Fetch the 'concern' match list (关注赛事)."""
    return _get(API_MATCH_LIST, params={"method": "concern"})


def fetch_fixed_bonus(match_id: str | int) -> tuple[dict | None, str | None]:
    """Fetch full SP odds for a single match."""
    return _get(API_FIXED_BONUS, params={"clientCode": "3001", "matchId": str(match_id)})


def fetch_result_list(
    *,
    page_size: int = 20,
    page_no: int | None = None,
    match_date: str | None = None,
) -> tuple[dict | None, str | None]:
    """Fetch result list from the football data result tab."""
    params = {"method": "result", "pageSize": str(page_size)}
    if page_no is not None:
        params["pageNo"] = str(page_no)
    if match_date:
        params["matchDate"] = match_date
    return _get(API_RESULT_LIST, params=params)
