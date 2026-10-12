"""Summarise the loop 01 survey against the learner's predictions."""
import json
import statistics as st
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent.parent / "data" / "loops" / "01-one-base" / "survey-2026-09-15.json"


def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None


def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = rank(x), rank(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def f(v, w=6, d=2):
    return f"{v:>{w}.{d}f}" if isinstance(v, (int, float)) else f"{'—':>{w}}"


data = json.loads(PATH.read_text())
E = data["edits"]
print("window", data["window"])
noise = [e["upstream_abs"] / e["pos"] for e in E if e["pos"]]
print(f"noise floor: mean |Δ| per base before the edit = {st.median(noise):.4f} bits (median over edits). Not a causal leak;")
print("  Evo 2 computes the whole window in bfloat16, so any change nudges every value (probe, 15 Sep). Read downstream bins against it.")
print("  'reach' is inflated by noise spikes: use the bins and the synonymous control instead.\n")

groups = {}
for e in E:
    groups.setdefault((e["region"], e["kind"]), []).append(e)

print(f"{'region':<13}{'kind':<24}{'n':>4}{'local':>8}{'6-30':>8}{'30-100':>8}{'100-300':>8}{'300-600':>8}{'reach':>7}{'≥100':>6}")
print(f"{'':<37}{'Σbits':>8}{'bits/base, median':>32}{'':>8}{'med':>7}{'frac':>6}")
for (region, kind), es in sorted(groups.items()):
    b = {k: med([e["bins"][k] for e in es]) for k in ("6-30", "30-100", "100-300", "300-600")}
    far = sum(e["reach"] >= 100 for e in es) / len(es)
    print(f"{region:<13}{kind:<24}{len(es):>4}{f(med([e['local'] for e in es]), 8)}"
          f"{f(b['6-30'], 8, 3)}{f(b['30-100'], 8, 3)}{f(b['100-300'], 8, 3)}{f(b['300-600'], 8, 3)}"
          f"{f(med([e['reach'] for e in es]), 7, 0)}{f(far, 6, 2)}")

print("\nTransitions vs transversions (substitutions), median local Σbits:")
for region in ("coding", "between ORFs"):
    for kind in sorted({e["kind"] for e in E if e["region"] == region and e["type"] == "sub"}):
        es = [e for e in E if e["region"] == region and e["kind"] == kind and e["type"] == "sub"]
        ti = [e["local"] for e in es if e.get("ti")]
        tv = [e["local"] for e in es if e.get("ti") is False]
        print(f"  {region:<13}{kind:<14} transitions n={len(ti):>3} {f(med(ti))}   transversions n={len(tv):>3} {f(med(tv))}")

print("\nSynonymous swaps by codon position, median local Σbits:")
for k in (1, 2, 3):
    es = [e["local"] for e in E if e["kind"] == "synonymous" and e["codon_pos"] == k]
    print(f"  position {k}: n={len(es):>3} {f(med(es))}")

mis = [e for e in E if e["kind"] == "missense"]
if len(mis) > 3:
    print(f"\nMissense (n={len(mis)}): Spearman, BLOSUM62 similarity vs local Σbits = {f(spearman([e['blosum'] for e in mis], [e['local'] for e in mis]), 5)}"
          f"; vs downstream Σbits = {f(spearman([e['blosum'] for e in mis], [e['downstream_sum'] for e in mis]), 5)}")
    print("  (negative = more similar amino acids are less surprising)")

if "--json" in sys.argv:
    print(json.dumps({str(k): len(v) for k, v in groups.items()}))
