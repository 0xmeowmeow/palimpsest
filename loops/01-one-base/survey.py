"""Loop 01 survey: test the learner's predictions across many edits at once.

Uses the running One base server (it holds the only copy of Evo 2 on the GPU).
Deterministic: fixed window, fixed random seed, and repeat scoring is bit-identical.

Run with the evo2 env's Python, which has Biopython for BLOSUM62:
    /home/meow/miniconda3/envs/evo2/bin/python loops/01-one-base/survey.py
"""
import json
import random
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from Bio.Align import substitution_matrices

U = "http://127.0.0.1:8770"
OUT = Path(__file__).resolve().parent.parent.parent / "data" / "loops" / "01-one-base" / "survey-2026-09-15.json"
WS, WL = 700, 1990          # ECOLAC bases 701–2690; leaves room for an insertion under the 2,000-base cap
LN2 = 0.6931471805599453
BLOSUM = substitution_matrices.load("BLOSUM62")
PURINES = set("AG")

B = "TCAG"
AA = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODE = {x + y + z: AA[16 * B.index(x) + 4 * B.index(y) + B.index(z)] for x in B for y in B for z in B}
RC = str.maketrans("ACGT", "TGCA")


def get(path):
    return json.load(urllib.request.urlopen(U + path, timeout=30))


def score(seq, label):
    req = urllib.request.Request(U + "/score", data=json.dumps({"seq": seq, "label": label}).encode(),
                                 headers={"Content-Type": "application/json"})
    lp = json.load(urllib.request.urlopen(req, timeout=300))["lp"]
    return [None if v is None else -v / LN2 for v in lp]


def orfs(seq, min_codons=100):
    """ATG→stop ORFs on both strands, as (start, end) in + strand coordinates, end exclusive."""
    out = []
    for strand, s in (("+", seq), ("-", seq.translate(RC)[::-1])):
        for f in range(3):
            i = f
            while i + 3 <= len(s):
                if s[i:i + 3] == "ATG":
                    k = i
                    while k + 3 <= len(s) and CODE[s[k:k + 3]] != "*":
                        k += 3
                    end = min(k + 3, len(s))
                    if (end - i) // 3 >= min_codons:
                        out.append((strand, i, end) if strand == "+" else (strand, len(s) - end, len(s) - i))
                    i = end
                else:
                    i += 3
    return out


def b2a(j, ed):
    t, p = ed["type"], ed["pos"]
    if t == "sub":
        return j
    if t == "ins":
        return j if j < p else (None if j == p else j - 1)
    if t == "del":
        return j if j < p else j + 1
    if t == "del3":
        return j if j < p else j + 3


def measure(a_bits, b_bits, ed):
    n, p = len(a_bits), ed["pos"]
    bA = [None] * n
    for j, v in enumerate(b_bits):
        a = b2a(j, ed)
        if a is not None and a < n:
            bA[a] = v
    d = [None if (x is None or y is None) else y - x for x, y in zip(a_bits, bA)]
    up = sum(abs(v) for v in d[:p] if v is not None)
    def total(lo, hi):
        vals = [v for v in d[max(0, lo):min(n, hi)] if v is not None]
        return sum(vals), len(vals)
    local, _ = total(p, p + 6)
    bins = {}
    for name, lo, hi in (("6-30", 6, 30), ("30-100", 30, 100), ("100-300", 100, 300), ("300-600", 300, 600)):
        s, c = total(p + lo, p + hi)
        bins[name] = s / c if c else None
    # reach: furthest distance where the 30-base rolling mean of |Δ| exceeds 0.05 bits/base
    reach = 0
    for q in range(p, min(n, p + 900)):
        w = [abs(v) for v in d[q:q + 30] if v is not None]
        if w and sum(w) / len(w) > 0.05:
            reach = q - p
    return {"upstream_abs": up, "local": local, "bins": bins, "reach": reach,
            "downstream_sum": total(p + 6, n)[0]}


def main():
    full = get("/seq")["seq"]
    A = full[WS:WS + WL]
    all_orfs = orfs(full)
    main_orf = next(o for o in all_orfs if o[0] == "+" and o[1] <= WS + 750 < o[2] and o[2] - o[1] > 2000)
    o_s = main_orf[1] - WS
    coding = set()
    for _, s, e in all_orfs:
        coding.update(range(max(s, WS) - WS, min(e, WS + WL) - WS))
    rng = random.Random(15)

    a_bits = score(A, "survey baseline")
    assert a_bits == score(A, "survey baseline repeat"), "baseline not repeatable"

    edits = []
    codon_starts = [o_s + 3 * c for c in range((900 - o_s) // 3 + 1, (1400 - o_s) // 3)]
    for cs in rng.sample(codon_starts, 25):
        cod = A[cs:cs + 3]
        for k in range(3):
            for alt in "ACGT":
                if alt == cod[k]:
                    continue
                new = cod[:k] + alt + cod[k + 1:]
                aa0, aa1 = CODE[cod], CODE[new]
                kind = "synonymous" if aa0 == aa1 else ("stop" if aa1 == "*" else "missense")
                edits.append({"type": "sub", "pos": cs + k, "base": alt, "region": "coding", "kind": kind,
                              "codon_pos": k + 1, "aa": f"{aa0}>{aa1}",
                              "ti": (cod[k] in PURINES) == (alt in PURINES),
                              "blosum": None if kind != "missense" else float(BLOSUM[aa0][aa1])})
    for p in rng.sample(range(900, 1400), 15):
        edits.append({"type": "ins", "pos": p, "base": rng.choice("ACGT"), "region": "coding", "kind": "frameshift +1"})
    for p in rng.sample(range(900, 1400), 15):
        edits.append({"type": "del", "pos": p, "region": "coding", "kind": "frameshift -1"})
    for cs in rng.sample(codon_starts, 10):
        edits.append({"type": "del3", "pos": cs, "region": "coding", "kind": "in-frame codon deletion"})
    gap = [i for i in range(300, 750) if i not in coding]
    for p in rng.sample(gap, min(15, len(gap))):
        for alt in "ACGT":
            if alt != A[p]:
                edits.append({"type": "sub", "pos": p, "base": alt, "region": "between ORFs", "kind": "substitution",
                              "ti": (A[p] in PURINES) == (alt in PURINES)})
    for p in rng.sample(gap, min(8, len(gap))):
        edits.append({"type": "ins", "pos": p, "base": rng.choice("ACGT"), "region": "between ORFs", "kind": "insertion"})
    for p in rng.sample(gap, min(8, len(gap))):
        edits.append({"type": "del", "pos": p, "region": "between ORFs", "kind": "deletion"})

    for i, ed in enumerate(edits):
        p, t = ed["pos"], ed["type"]
        if t == "sub":
            seq = A[:p] + ed["base"] + A[p + 1:]
        elif t == "ins":
            seq = A[:p] + ed["base"] + A[p:]
        elif t == "del":
            seq = A[:p] + A[p + 1:]
        else:
            seq = A[:p] + A[p + 3:]
        ed.update(measure(a_bits, score(seq, f"survey {i} {ed['kind']} at {p + 1}"), ed))
        if i % 25 == 0 or i == len(edits) - 1:
            print(f"{i + 1}/{len(edits)}", flush=True)
            save(edits[:i + 1], gap, o_s, complete=i == len(edits) - 1)


def save(done, gap, o_s, complete):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "complete": complete,
        "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {"source": "ECOLAC", "start_1based": WS + 1, "length": WL,
                   "main_orf_window_start": o_s, "gap_positions": [min(gap), max(gap)] if gap else None},
        "edits": done}, indent=1))


if __name__ == "__main__":
    main()
