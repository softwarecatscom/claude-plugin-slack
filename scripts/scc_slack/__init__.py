"""Shared library for scc-slack plugin scripts."""

from scc_slack.client import SlackClient, load_token
from scc_slack.config import load_config
from scc_slack.filter import classify_message, filter_messages
from scc_slack.identity import load_identity
from scc_slack.resolve import resolve_channel, resolve_user
from scc_slack.seen import load_seen, save_seen

__all__ = [
    "SlackClient",
    "classify_message",
    "filter_messages",
    "load_config",
    "load_identity",
    "load_seen",
    "load_token",
    "resolve_channel",
    "resolve_user",
    "save_seen",
]
