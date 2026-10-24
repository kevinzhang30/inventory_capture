"""Generate a frozen golden set of synthetic packing slips: <name>.png + <name>.truth.json.

    python -m evalkit.generate_golden --out eval/golden --count 100 --seed 7

Real slips (photographed, hand-labelled) can be added alongside with the same naming convention.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from capture_client.slips import random_truth, render_packing_slip
from seed.seed import SUPPLIERS, parts


def generate(out: Path, count: int, seed: int, n_parts: int = 2000) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    catalog = parts(n_parts, random.Random(42))  # identical to the database seed
    suppliers = dict(SUPPLIERS)
    written = []
    for i in range(count):
        truth = random_truth(rng, catalog, suppliers=suppliers)
        name = f"slip_{seed}_{i:04d}"
        (out / f"{name}.png").write_bytes(render_packing_slip(truth, seed=rng.randint(0, 1 << 30)))
        (out / f"{name}.truth.json").write_text(json.dumps(truth, indent=2))
        written.append(out / f"{name}.png")
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("eval/golden"))
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    print(f"wrote {len(generate(args.out, args.count, args.seed))} slips to {args.out}")


if __name__ == "__main__":
    main()
