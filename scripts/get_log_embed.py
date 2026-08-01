#!/usr/bin/env python3
"""Download or clear log.csv on the T-Embed CC1101 task tracker over the local network."""

import argparse
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


def download_log(ip: str, out_path: Path, timeout: float = 10.0) -> None:
    url = f"http://{ip}/log.csv"
    print(f"Fetching {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        print(f"Failed to reach device: {e}", file=sys.stderr)
        sys.exit(1)

    out_path.write_bytes(data)
    print(f"Saved {len(data)} bytes to {out_path}")


def clear_log(ip: str, timeout: float = 10.0) -> None:
    url = f"http://{ip}/log.csv"
    print(f"Sending DELETE to {url} ...")
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            print(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"Failed to reach device: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Sync or clear log.csv on T-Embed task tracker"
    )
    parser.add_argument(
        "ip", help="IP address shown on the device's Settings > Sync with PC screen"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="log.csv",
        help="Output file path (default: ./log.csv)",
    )
    parser.add_argument(
        "--timestamped",
        action="store_true",
        help="Save with a timestamp suffix instead of overwriting",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Delete the log on the device instead of downloading it",
    )
    args = parser.parse_args()

    out_path = Path(args.output)
    if args.timestamped:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_path.with_stem(f"{out_path.stem}_{stamp}")

    download_log(args.ip, out_path)
    if args.clear:
        confirm = input(
            f"This will permanently erase log.csv on {args.ip}. Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Cancelled.")
            return
        clear_log(args.ip)
        return


if __name__ == "__main__":
    main()
