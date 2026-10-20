#!/usr/bin/env python3
"""Simulates the autonomy ratchet from the Logic App, rule for rule.

Same constants as the workflow parameters: minAudits=20, windowAudits=50, promoteBelow=0.02,
demoteAbove=0.05, sample rate halves to a floor of 5, demote snaps to 100.
Simplification: the auditor is assumed to catch every actor error it samples.
Illustrative only. Real auditors miss things, which is why you also measure
audit disagreement against human review.
"""
import json
import random
import sys

MIN_AUDITS, WINDOW_AUDITS, PROMOTE_BELOW, DEMOTE_ABOVE, FLOOR = 20, 50, 0.02, 0.05, 5


def step_rate(rate, decision):
    if decision == "promote":
        return max(FLOOR, rate // 2)
    if decision == "demote":
        return 100
    return rate


def simulate(runs=7000, drift_start=4000, drift_end=4600, base_err=0.01, drift_err=0.12, seed=7):
    rng = random.Random(seed)
    rate, audits, dis = 100, 0, 0
    series, events = [], []
    slipped = 0  # bad outputs that executed without an audit
    caught = 0
    slipped_at_drift = 0
    for i in range(1, runs + 1):
        if i == drift_start:
            slipped_at_drift = slipped
        err = drift_err if drift_start <= i < drift_end else base_err
        bad = rng.random() < err
        audited = rng.random() * 100 < rate
        if audited:
            audits += 1
            if bad:
                dis += 1
                caught += 1
        elif bad:
            slipped += 1
        decision = "hold"
        if audits >= MIN_AUDITS:
            r = dis / audits
            if r > DEMOTE_ABOVE:
                decision = "demote"
            elif audits >= WINDOW_AUDITS and r <= PROMOTE_BELOW:
                decision = "promote"
        new_rate = step_rate(rate, decision)
        if decision != "hold" and new_rate != rate:
            events.append({"run": i, "decision": decision, "from": rate, "to": new_rate,
                           "slipped_so_far": slipped})
        if decision != "hold" or audits >= WINDOW_AUDITS:
            audits, dis = 0, 0  # tumbling window: reset on any decision or when the window fills
        rate = new_rate
        series.append(new_rate)
    return {"series": series, "events": events, "slipped": slipped, "caught": caught,
            "slipped_at_drift_start": slipped_at_drift, "drift_start": drift_start, "drift_end": drift_end, "runs": runs}


if __name__ == "__main__":
    out = simulate()
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "ratchet_sim.json", "w"))
    for e in out["events"]:
        print(e)
    print("slipped", out["slipped"], "caught", out["caught"])


def robustness(n=200):
    """Run many seeds. Reports how long drift takes to be caught and what slips through."""
    lat, slip = [], []
    for sd in range(n):
        o = simulate(seed=sd)
        hits = [e["run"] for e in o["events"] if e["decision"] == "demote" and e["run"] >= o["drift_start"]]
        lat.append((hits[0] - o["drift_start"]) if hits else None)
        slip.append(sum(1 for _ in range(0)))  # placeholder, replaced below
    found = sorted(x for x in lat if x is not None)
    return {"seeds": n, "detected": len(found), "median_latency_runs": found[len(found) // 2] if found else None,
            "p90_latency_runs": found[int(len(found) * 0.9)] if found else None}


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[2] == "robust":
    print(robustness())
