"""Nạp policy.yaml — nguồn ngưỡng duy nhất mà API, guardrail và reviewer cùng dùng."""
from __future__ import annotations

from functools import lru_cache

import yaml

from .config import settings


@lru_cache(maxsize=1)
def get_policy() -> dict:
    with open(settings.policy_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def approval_rule(rule_id: str) -> dict:
    for rule in get_policy()["approval_required"]:
        if rule["id"] == rule_id:
            return rule
    raise KeyError(rule_id)


def describe_rules(rule_ids: list[str]) -> list[dict]:
    return [approval_rule(r) for r in dict.fromkeys(rule_ids)]


def refund_threshold() -> int:
    return int(get_policy()["refund"]["auto_approve_max_vnd"])
