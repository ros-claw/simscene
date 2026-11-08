#!/usr/bin/env python3
"""Aggregate a frozen evaluator's actual per-step functional progress flags.

Input CSV: step,role_1,role_2,... ; one row for every interval [step,step+1).
All data must already have been derived independently from simulator motion,
allowed causal windows and frozen thresholds. This code neither extracts
physics nor verifies causation, representation fidelity or scene completion.
"""
import argparse
import csv
import io
import json
import math
from pathlib import Path

def intervals(stream, start, end, hz):
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise ValueError("invalid half-open physics-step interval")
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError("hz must be finite and positive")
    rd = csv.DictReader(stream)
    cols = rd.fieldnames or []
    if len(cols) < 2 or cols[0] != "step" or len(cols) != len(set(cols)) or any(not c.strip() for c in cols):
        raise ValueError("expected step followed by distinct, nonempty audited role IDs")
    expected, active, gap, max_gap = start, 0, 0, 0
    for row in rd:
        if None in row or expected >= end or int(row["step"]) != expected:
            raise ValueError("input must contain exactly the requested ordered steps")
        flags = [row[c] for c in cols[1:]]
        if any(v not in ("0", "1") for v in flags):
            raise ValueError("role flags must be 0 or 1; missing samples are not inactive")
        if "1" in flags:
            active += 1
            gap = 0
        else:
            gap += 1
            max_gap = max(max_gap, gap)
        expected += 1
    if expected != end:
        raise ValueError("missing physics steps")
    n=end-start
    return {"span_s":n/hz, "net_progress_s":active/hz, "fraction":active/n,
            "longest_idle_s":max_gap/hz, "step_intervals":n, "active_step_intervals":active}

def evaluate(d, limits):
    return {"span": d["span_s"] >= limits["min_span_s"],
            "active": d["net_progress_s"] >= limits["min_net_progress_s"],
            "fraction": d["fraction"] >= limits["min_fraction"],
            "longest_idle": d["longest_idle_s"] <= limits["max_idle_s"]}

def self_test():
    raw="step,ball,drawer\n10,1,1\n11,1,0\n12,0,0\n13,0,0\n14,0,1\n"
    d=intervals(io.StringIO(raw),10,15,2)
    assert d["net_progress_s"] == 1.5 and d["span_s"] == 2.5 and d["longest_idle_s"] == 1
    for bad in (raw.replace("11,1,0\n",""),raw.replace("13,0,0","12,0,0"),
                raw.replace("10,1,1","10,1,"),raw+"15,0,0\n"):
        try:
            intervals(io.StringIO(bad),10,15,2)
        except (TypeError,ValueError):
            continue
        raise AssertionError("invalid source accepted")
    assert evaluate({"span_s":50,"net_progress_s":45,"fraction":.9,"longest_idle_s":2},
                    {"min_span_s":50,"min_net_progress_s":45,"min_fraction":.85,"max_idle_s":2}) == dict.fromkeys(("span","active","fraction","longest_idle"), True)
    print("Self-test passed: overlap counted once; exact gaps; incomplete, duplicate, blank or extra samples rejected.")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv",nargs="?")
    p.add_argument("--hz",type=float)
    p.add_argument("--start-step",type=int)
    p.add_argument("--end-step",type=int)
    p.add_argument("--criteria",default=str(Path(__file__).with_name("acceptance.proposal.json")))
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test()
        return 0
    if any(v is None for v in (a.csv,a.hz,a.start_step,a.end_step)):
        p.error("require CSV, --hz, --start-step and --end-step")
    with open(a.csv,newline="",encoding="utf-8-sig") as f:
        d=intervals(f,a.start_step,a.end_step,a.hz)
    limits=json.loads(Path(a.criteria).read_text(encoding="utf-8"))["timing"]
    gates=evaluate(d,limits)
    print(json.dumps({"scope":"Motion-clock aggregation only; never a physical validation result",
                      "metrics":d,"timing_checks":gates,"timing_passed":all(gates.values())},indent=2))
    return 0 if all(gates.values()) else 1

if __name__=="__main__":
    raise SystemExit(main())
