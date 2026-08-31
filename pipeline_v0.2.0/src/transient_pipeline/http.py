from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

import requests


class RetryableRemoteError(RuntimeError):
    pass


class InvalidRemotePayload(RetryableRemoteError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0
    timeout_s: float = 45.0


class ValidatedSession:
    def __init__(self, policy: RetryPolicy | None = None, user_agent: str = "historical-transient-pipeline/0.1"):
        self.policy = policy or RetryPolicy()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def request(self, method: str, url: str, *, validator: Callable[[requests.Response], None] | None = None, **kwargs):
        last: Exception | None = None
        kwargs.setdefault("timeout", self.policy.timeout_s)
        for attempt in range(1, self.policy.attempts + 1):
            try:
                r = self.session.request(method, url, **kwargs)
                if r.status_code >= 500 or r.status_code == 429:
                    raise RetryableRemoteError(f"HTTP {r.status_code}")
                if r.status_code != 200:
                    raise InvalidRemotePayload(f"unexpected HTTP {r.status_code}: {r.text[:300]}")
                if validator:
                    validator(r)
                return r
            except (requests.RequestException, RetryableRemoteError, InvalidRemotePayload) as exc:
                last = exc
                if attempt == self.policy.attempts:
                    break
                delay = min(self.policy.max_delay_s, self.policy.base_delay_s * (2 ** (attempt - 1)))
                time.sleep(delay)
        raise RetryableRemoteError(str(last) if last else "remote request failed")
