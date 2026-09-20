from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from ..normalize import normalize_jev_response
from ..rubric import build_questions
from ..schema import ReviewState, Scorecard

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"


class JevError(RuntimeError):
    pass


class JevEvaluator:
    id = "jev"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("JEV_API_KEY", "")).strip()
        if not self.api_key:
            raise JevError("JEV_API_KEY is required for Jev evaluation")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None

    def evaluate(self, state: ReviewState) -> Scorecard:
        payload = {"state": state.model_dump(), "model": JEV_MODEL, "questions": build_questions()}
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(
                    JEV_ENDPOINT,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.TimeoutException as error:
                raise JevError(f"Jev did not respond within {self.timeout_seconds:g}s") from error
            except httpx.HTTPError as error:
                raise JevError("Could not reach the Jev API") from error
            if response.is_success:
                try:
                    body: dict[str, Any] = response.json()
                    return normalize_jev_response(body)
                except (ValueError, TypeError) as error:
                    raise JevError("Jev returned an invalid response") from error
            if _retryable(response.status_code) and attempt < self.max_retries:
                time.sleep(_retry_delay(response.headers.get("retry-after"), attempt))
                continue
            raise JevError(_status_message(response))
        raise JevError("Jev request failed after retries")

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> JevEvaluator:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _retryable(status: int) -> bool:
    return status in {429, 529} or status >= 500


def _retry_delay(value: str | None, attempt: int) -> float:
    if value:
        try:
            return min(max(float(value), 0), 5)
        except ValueError:
            try:
                return min(max(parsedate_to_datetime(value).timestamp() - time.time(), 0), 5)
            except (TypeError, ValueError, OverflowError):
                pass
    return 0.25 * 2**attempt


def _status_message(response: httpx.Response) -> str:
    if response.status_code == 400:
        try:
            if response.json().get("detail", {}).get("error_type") == "max_tokens_exceeded":
                return "Jev input limit was exceeded"
        except (ValueError, AttributeError):
            pass
    messages = {
        401: "Jev rejected JEV_API_KEY",
        422: "Jev rejected the evaluation request",
        429: "Jev rate-limited the request after retries",
        529: "Jev remained overloaded after retries",
    }
    return messages.get(
        response.status_code, f"Jev API request failed with HTTP {response.status_code}"
    )
