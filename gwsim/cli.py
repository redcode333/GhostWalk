"""python -m gwsim.cli --out data/  -> writes the frozen dev/test companies."""
from __future__ import annotations
import argparse, json, pathlib
import numpy as np
from .world import build_company, Knobs

def splits():
    rng = np.random.default_rng(20261115)
    dev = [("layered", 1000 + i) for i in range(5)] + [("hub", 2000 + i) for i in range(5)]
    test = ([("layered", 3000 + i) for i in range(10)] + [("hub", 4000 + i) for i in range(10)]
            + [("real", 5000 + i) for i in range(10)])
    sizes = {s: int(rng.integers(30, 121)) for _, s in dev + test}
    return dev, test, sizes

def make(family, seed, size, knobs=None):
    real = ["online-boutique", "sock-shop"][seed % 2] if family == "real" else None
    return build_company(f"{family}-{seed}", family, seed, n=size, knobs=knobs, real=real)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    dev, test, sizes = splits()
    for split, items in (("dev", dev), ("test", test)):
        d = out / split; d.mkdir(exist_ok=True)
        for fam, seed in items:
            co = make(fam, seed, sizes[seed])
            (d / f"{co.name}.json").write_text(co.to_json())
            print(split, co.name, len(co.components), "components", len(co.true_edges), "edges",
                  len(co.hidden_edges), "hidden")

if __name__ == "__main__":
    main()
