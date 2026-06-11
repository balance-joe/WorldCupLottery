"""Sporttery API client. Returns raw JSON dicts."""

from __future__ import annotations

import time

import requests

from src.config import (
    API_FUTURE_MATCHES,
    API_FIXED_BONUS,
    API_INJURY_SUSPENSION,
    API_MATCH_LIST,
    API_MATCH_FEATURE,
    API_MATCH_HEAD,
    API_MATCH_PLAYER,
    API_MATCH_RESULT,
    API_MATCH_TABLES,
    API_RESULT_LIST,
    API_RESULT_HISTORY,
    API_SAME_ODDS,
    REQUEST_TIMEOUT,
    SPORTTERY_HEADERS,
    API_TEAM_POOLDIV_STATS,
)

# Retry defaults
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubles each retry: 1s, 2s, 4s

DETAIL_APIS = {
    "matchHead": API_MATCH_HEAD,
    "matchFeature": API_MATCH_FEATURE,
    "matchResult": API_MATCH_RESULT,
    "resultHistory": API_RESULT_HISTORY,
    "futureMatches": API_FUTURE_MATCHES,
    "matchTables": API_MATCH_TABLES,
    "matchPlayer": API_MATCH_PLAYER,
    "injurySuspension": API_INJURY_SUSPENSION,
    "sameOdds": API_SAME_ODDS,
    "teamPooldivStats": API_TEAM_POOLDIV_STATS,
}


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


def fetch_detail_api(
    source_name: str,
    match_id: str | int,
    *,
    extra_params: dict | None = None,
) -> tuple[dict | None, str | None]:
    """Fetch one football detail endpoint by source name."""
    url = DETAIL_APIS.get(source_name)
    if not url:
        return None, f"unsupported detail api: {source_name}"
    params = {"matchId": str(match_id)}
    if extra_params:
        params.update(extra_params)
    return _get(url, params=params)


def fetch_match_detail_bundle(
    match_id: str | int,
    *,
    sources: tuple[str, ...] | list[str] | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Fetch a bundle of football detail endpoints.

    Returns `(payloads, errors)`.
    """
    selected = tuple(sources) if sources else tuple(DETAIL_APIS.keys())
    payloads: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for source_name in selected:
        data, err = fetch_detail_api(source_name, match_id)
        if err:
            errors[source_name] = err
        elif data is not None:
            payloads[source_name] = data
    return payloads, errors
