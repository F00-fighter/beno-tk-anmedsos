"""Run the YouTube collector with versioned raw, interim, and processed data."""

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas
import requests


ROOT = Path(__file__).resolve().parent
COLLECTOR = ROOT / "youtubeAPI1-Vids.py"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def count_csv_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        return sum(1 for _ in csv.DictReader(source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("discover", "collect"), required=True)
    parser.add_argument("--candidates", type=Path, help="CSV from discovery, optionally edited for selection")
    args = parser.parse_args()
    if args.candidates and args.mode != "collect":
        parser.error("--candidates is only used with --mode collect")
    if not os.environ.get("YOUTUBE_API_KEY"):
        parser.error("Set YOUTUBE_API_KEY in this shell before running")
    candidates_path = None
    if args.candidates:
        candidates_path = args.candidates.resolve()
        if not candidates_path.is_file():
            parser.error(f"Candidates CSV not found: {candidates_path}")

    run_root = ROOT / "runs"
    run_root.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = run_root / run_id
    run_dir.mkdir()
    raw_dir = ROOT / "data" / "raw" / run_id
    interim_dir = ROOT / "data" / "interim" / run_id
    processed_dir = ROOT / "data" / "processed" / run_id
    for directory in (raw_dir, interim_dir, processed_dir):
        directory.mkdir(parents=True)
    started = timestamp()
    shutil.copy2(COLLECTOR, run_dir / COLLECTOR.name)
    candidates_sha256 = None
    if candidates_path:
        candidates_sha256 = sha256(candidates_path)
        shutil.copy2(candidates_path, interim_dir / "candidates_youtube.csv")

    environment = os.environ.copy()
    environment["MBG_MODE"] = args.mode
    environment["MBG_RAW_LOG"] = str(raw_dir / "youtube_api_responses.jsonl")
    environment["MBG_INTERIM_DIR"] = str(interim_dir)
    environment["MBG_PROCESSED_DIR"] = str(processed_dir)
    environment["MBG_CANDIDATES_CSV"] = str(interim_dir / "candidates_youtube.csv")
    print(f"Run: {run_dir}", flush=True)
    print(f"Data: {raw_dir} | {interim_dir} | {processed_dir}", flush=True)
    with (run_dir / "collection.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(run_dir / COLLECTOR.name)],
                                   cwd=run_dir, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace")
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return_code = process.wait()
    artifact_dirs = (run_dir, raw_dir, interim_dir, processed_dir)
    files = {str(path.relative_to(ROOT)): {"sha256": sha256(path), "bytes": path.stat().st_size}
             for directory in artifact_dirs for path in directory.iterdir() if path.is_file()}
    log_text = (run_dir / "collection.log").read_text(encoding="utf-8")
    status = ("failed" if return_code else
              "partial_quota" if "[STOP] Quota exhausted" in log_text or "[STOP] Daily quota" in log_text else
              "completed_with_warnings" if "[WARN]" in log_text else "completed")
    row_counts = {str(path.relative_to(ROOT)): count_csv_rows(path)
                  for directory in (interim_dir, processed_dir) for path in directory.glob("*.csv")}
    manifest = {
        "run_id": run_id,
        "started_at_utc": started,
        "finished_at_utc": timestamp(),
        "mode": args.mode,
        "status": status,
        "exit_code": return_code,
        "candidate_input_sha256": candidates_sha256,
        "python_version": platform.python_version(),
        "dependencies": {"pandas": pandas.__version__, "requests": requests.__version__},
        "csv_rows": row_counts,
        "files": files,
        "note": "Parameters and filters are frozen in the copied collector. API responses are saved as parsed JSON with request parameters, excluding the API key. A zero exit code does not guarantee a complete sample; check collector output and API errors.",
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
