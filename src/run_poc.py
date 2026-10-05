"""PoC orchestration: spec -> BPMN -> (UIA build) -> (SQL verify) -> report.

Stages that need Windows + Bizagi Studio are reported as SKIPPED on other
platforms or until their modules exist, so the pipeline runs end to end today.

Usage (from the repo root):
    python -m src.run_poc                 # sample spec, writes out/
    python -m src.run_poc --out out --no-preview
"""

from __future__ import annotations

import argparse
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from src.bpmn.bpmn_builder import write_bpmn
from src.bpmn.preview import write_preview
from src.design_layer.sample_purchase import build_sample_purchase


@dataclass
class StageResult:
    name: str
    status: str  # OK / FAILED / SKIPPED
    detail: str = ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    ap.add_argument("--no-preview", action="store_true", help="skip the HTML preview")
    args = ap.parse_args(argv)
    out = Path(args.out)
    results: list[StageResult] = []

    try:
        spec = build_sample_purchase()
        (out / "spec.json").parent.mkdir(parents=True, exist_ok=True)
        (out / "spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        results.append(StageResult("1. design spec (sample)", "OK",
                                   f"{len(spec.entities)} entities, {len(spec.forms)} forms, "
                                   f"{len(spec.rules)} rules, {len(spec.roles)} roles -> {out / 'spec.json'}"))
    except Exception as exc:  # noqa: BLE001 - report and stop
        results.append(StageResult("1. design spec (sample)", "FAILED", str(exc)))
        return _report(results)

    try:
        path = write_bpmn(spec, out / f"{spec.name}.bpmn")
        results.append(StageResult("2. BPMN 2.0 export", "OK", f"{path} (import into Bizagi Modeler)"))
    except Exception as exc:  # noqa: BLE001
        results.append(StageResult("2. BPMN 2.0 export", "FAILED", str(exc)))

    if not args.no_preview:
        try:
            path = write_preview(spec, out / "preview.html")
            results.append(StageResult("   HTML preview", "OK", str(path)))
        except Exception as exc:  # noqa: BLE001
            results.append(StageResult("   HTML preview", "FAILED", str(exc)))

    on_windows = platform.system() == "Windows"
    why = "not implemented yet" if on_windows else "needs Windows + Bizagi Studio"
    results.append(StageResult("3. UIA build (data model, forms, rules)", "SKIPPED", why))
    results.append(StageResult("4. SQL read-only verification", "SKIPPED", why))
    return _report(results)


def _report(results: list[StageResult]) -> int:
    print("\nBizagi agent PoC — report")
    print("-" * 60)
    for r in results:
        print(f"[{r.status:^7}] {r.name}" + (f"\n          {r.detail}" if r.detail else ""))
    print("-" * 60)
    return 1 if any(r.status == "FAILED" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
