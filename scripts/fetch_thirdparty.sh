#!/usr/bin/env bash
# Usage: scripts/fetch_thirdparty.sh <name> <url> <sha256>
# Fetches a third-party file (e.g. zexdoc, GPL) into build/third_party/<name>, verifying the hash.
# Never committed (rule 9): build/ is gitignored. Prints the path. Cached across runs.
set -eu
cd "$(git rev-parse --show-toplevel)"
name=$1 url=$2 sha=$3; dir=build/third_party; mkdir -p "$dir"; f="$dir/$name"
if [ ! -f "$f" ] || [ "$(sha256sum "$f" | cut -d' ' -f1)" != "$sha" ]; then
  curl -fsSL "$url" -o "$f.tmp"
  [ "$(sha256sum "$f.tmp" | cut -d' ' -f1)" = "$sha" ] || { rm -f "$f.tmp"; echo "sha256 mismatch for $name" >&2; exit 1; }
  mv "$f.tmp" "$f"
fi
echo "$f"
