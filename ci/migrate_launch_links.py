"""Migrate DataHub launch links in an existing rendered website without rebuilding."""

import argparse
import json
from pathlib import Path
import sys

from relocate_labs import update_datahub_links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument(
        "--expected-manifest", required=True,
        help="SHA-256 over sorted UTF-8 relative paths + NUL + ASCII file SHA-256 + LF; all files included",
    )
    args = parser.parse_args()
    try:
        report = update_datahub_links(args.site, args.expected_manifest)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Migration refused: {error}\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
