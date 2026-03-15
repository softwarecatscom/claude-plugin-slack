"""HTTP client for Slack API with proxy fallback."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import httpx

FALLBACK_COOLDOWN = 600  # 10 minutes
FALLBACK_STATE_FILE = Path.home() / ".claude" / "slack-proxy-fallback-alerted"


def load_token() -> str:
    """Load Slack token from slack-cli's .slack file."""
    slack_bin = shutil.which("slack")
    if not slack_bin:
        msg = "slack-cli not found in PATH"
        raise RuntimeError(msg)
    token_file = Path(slack_bin).parent / ".slack"
    if not token_file.exists():
        msg = "No Slack token found."
        raise RuntimeError(msg)
    return token_file.read_text().strip()


class SlackClient:
    """HTTP client for Slack API with proxy fallback."""

    def __init__(self, token: str, proxy_url: str | None = None) -> None:
        self.base_url = proxy_url or "https://slack.com"
        self.direct_url = "https://slack.com"
        self.using_proxy = self.base_url != self.direct_url
        self._client = httpx.Client(
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}"},
        )
        self._last_fallback_warn = 0.0

    def get(self, method: str, params: dict | None = None) -> dict:
        """Call a Slack API method with proxy fallback."""
        url = f"{self.base_url}/api/{method}"
        try:
            resp = self._client.get(url, params=params)
            return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            if not self.using_proxy:
                return {"ok": False, "error": str(exc)}
            self._fallback_warn(str(exc))
            try:
                url = f"{self.direct_url}/api/{method}"
                resp = self._client.get(url, params=params)
                return resp.json()
            except Exception as exc2:
                return {"ok": False, "error": str(exc2)}

    def _fallback_warn(self, reason: str) -> None:
        """Emit a proxy fallback warning with 10-minute cooldown."""
        now = time.time()
        if now - self._last_fallback_warn < FALLBACK_COOLDOWN:
            return
        self._last_fallback_warn = now
        import sys

        print(
            f"WARN: Proxy {self.base_url} unreachable ({reason}), falling back to direct Slack",
            file=sys.stderr,
        )
        FALLBACK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_STATE_FILE.write_text(str(int(now)))

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
