"""Routing *proposal* from Kev, and separate verified cascade policy.

Kev predictions are not guaranteed to measure LLM answer correctness. A human or
an independent task-specific verifier must provide the pass/fail decisions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kev_client import post_systemone

TIERS = ("l1", "l2", "l3")
ROUTE_QUESTION = {
    "start_tier": {
        "type": "choice",
        "instructions": (
            "Select the least capable tier likely to solve this user request. "
            "Choose l1 for simple extraction, easy classification or translation; "
            "l2 for moderate programming, reasoning or synthesis; "
            "l3 for complex multistep reasoning and advanced debugging. "
            "Do not assume the choice proves any model's correctness."
        ),
        "criteria": {
            "l1": "Small inexpensive LLM for simple, straightforward tasks",
            "l2": "Medium LLM for intermediate reasoning, programming and synthesis",
            "l3": "Strong reasoning LLM for difficult multistep tasks",
        },
    }
}


@dataclass(frozen=True)
class Route:
    tier: str
    proposed_tier: str
    p_max: float
    probabilities: dict[str, float]
    uncertain: bool
    latency_ms: float | None


def parse_route(response: dict, *, min_probability: float = 0.65, uncertain_tier: str = "l2") -> Route:
    if not 0.0 <= min_probability <= 1.0:
        raise ValueError("min_probability must be within [0, 1]")
    if uncertain_tier not in TIERS:
        raise ValueError(f"Invalid uncertain_tier: {uncertain_tier}")
    answer = response["answers"]["start_tier"]
    if answer.get("type") != "choice":
        raise ValueError("Expected choice answer")
    probs = answer.get("probabilities", {})
    if set(probs) != set(TIERS):
        raise ValueError("Unexpected model tier probability keys")
    probs = {k: float(probs[k]) for k in TIERS}
    if any(v < 0 or v > 1 for v in probs.values()) or not (0.98 <= sum(probs.values()) <= 1.02):
        raise ValueError("Malformed model probabilities")
    proposed = max(TIERS, key=probs.__getitem__)
    p_max = probs[proposed]
    uncertain = p_max < min_probability
    tier = uncertain_tier if uncertain else proposed
    raw_latency = response.get("latency_ms")
    return Route(tier, proposed, p_max, probs, uncertain, float(raw_latency) if raw_latency is not None else None)


def route_request(state: str, *, base_url: str = "http://127.0.0.1:8009", min_probability: float = 0.65) -> Route:
    response = post_systemone(state, ROUTE_QUESTION, base_url=base_url)
    return parse_route(response, min_probability=min_probability)


def next_tier(current: str, *, externally_verified_pass: bool) -> str | None:
    """Return None if finished, next tier if failed, or None at L3 (review needed).

    A `False` at L3 is **NOT** success. The caller must surface validation failure.
    """
    if current not in TIERS:
        raise ValueError(f"Unknown tier: {current}")
    if externally_verified_pass:
        return None
    idx = TIERS.index(current)
    return TIERS[idx + 1] if idx + 1 < len(TIERS) else None


def cascade(execute, verify, start_tier: str) -> dict:
    """Execute one tier at a time, requiring an INDEPENDENT verifier result.

    `execute(tier)` returns the answer; `verify(tier, answer)` returns True only
    after deterministic checking, grounded evaluation or human review.
    """
    if start_tier not in TIERS:
        raise ValueError(f"Invalid start tier: {start_tier}")
    attempts = []
    for tier in TIERS[TIERS.index(start_tier):]:
        answer = execute(tier)
        passed = verify(tier, answer)
        if not isinstance(passed, bool):
            raise TypeError("Verifier must return a boolean")
        attempts.append({"tier": tier, "verified": passed})
        if passed:
            return {"status": "verified", "tier": tier, "answer": answer, "attempts": attempts}
    return {"status": "review_required", "tier": None, "answer": None, "attempts": attempts}
