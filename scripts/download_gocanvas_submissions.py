"""Download full GoCanvas submissions listed in a JSON file.

The input is a JSON array of submission summaries (as returned by the GoCanvas
submissions list); only each item's `id` is used. Every submission is fetched from
`GET {base_url}/api/v3/submissions/{id}` and written to `{out_dir}/{id}.json`.
Files already present are skipped, so an interrupted run can be resumed.

The bearer token is read from GOCANVAS_TOKEN (preferred, keeps it out of shell
history) or --token.

    GOCANVAS_TOKEN=... pipenv run python scripts/download_gocanvas_submissions.py \
        submissions.json --out-dir docs/risk-submissions/downloads
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "https://api.gocanvas.com"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def load_ids(path: Path) -> list[int]:
    items = json.loads(path.read_text())
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a JSON array of submissions")
    ids = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise ValueError(f"{path}: item {index} has no integer 'id'")
        ids.append(item["id"])
    # Keep order, drop duplicates.
    return list(dict.fromkeys(ids))


def fetch_submission(client: httpx.Client, submission_id: int, max_attempts: int) -> dict:
    """GET one submission, retrying rate limits and server errors with backoff."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(f"/api/v3/submissions/{submission_id}")
        except httpx.TransportError as exc:
            if attempt == max_attempts:
                raise RuntimeError(f"network error: {exc}") from exc
            delay = 2**attempt
        else:
            if response.status_code == 200:
                return response.json()
            if response.status_code not in RETRY_STATUSES or attempt == max_attempts:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            retry_after = response.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else 2**attempt
        print(f"  {submission_id}: retrying in {delay}s (attempt {attempt}/{max_attempts})")
        time.sleep(delay)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("input", type=Path, help="JSON array of submission summaries")
    parser.add_argument("--out-dir", type=Path, default=Path("gocanvas-submissions"))
    parser.add_argument("--token", help="bearer token (default: $GOCANVAS_TOKEN)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between requests")
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()

    token = args.token or os.environ.get("GOCANVAS_TOKEN")
    if not token:
        parser.error("no bearer token: set GOCANVAS_TOKEN or pass --token")

    ids = load_ids(args.input)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(ids)} submissions -> {args.out_dir}")

    downloaded, skipped, failed = 0, 0, []
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=60) as client:
        for submission_id in ids:
            target = args.out_dir / f"{submission_id}.json"
            if target.exists() and not args.force:
                skipped += 1
                continue
            try:
                submission = fetch_submission(client, submission_id, args.max_attempts)
            except RuntimeError as exc:
                print(f"  {submission_id}: FAILED {exc}", file=sys.stderr)
                failed.append(submission_id)
                if "HTTP 401" in str(exc):
                    print("Token rejected; stopping.", file=sys.stderr)
                    break
                continue
            # Write to a temp file first so a crash never leaves a partial file behind.
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(submission, indent=4))
            tmp.replace(target)
            downloaded += 1
            print(f"  {submission_id}: ok")
            time.sleep(args.delay)

    print(f"done: {downloaded} downloaded, {skipped} skipped, {len(failed)} failed")
    if failed:
        print("failed ids: " + ", ".join(map(str, failed)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
