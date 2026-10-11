#!/usr/bin/env bash
# Adds ribbon/customUI14.xml to a .dotm that was saved from Word's VBA editor
# (Mac, or Windows without PowerShell).  Usage:
#
#   ./inject-ribbon.sh /path/to/LegalContractACG.dotm
#
# Then copy the .dotm into Word's startup folder (see docs/INSTALL-MAC.md).
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 LegalContractACG.dotm" >&2
  exit 1
fi

pkg="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
here="$(cd "$(dirname "$0")" && pwd)"
ribbon="$here/../ribbon/customUI14.xml"
[ -f "$pkg" ]    || { echo "not found: $pkg" >&2; exit 1; }
[ -f "$ribbon" ] || { echo "not found: $ribbon" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
unzip -q "$pkg" -d "$work"

mkdir -p "$work/customUI"
cp "$ribbon" "$work/customUI/customUI14.xml"

rels="$work/_rels/.rels"
if ! grep -q 'customUI14.xml' "$rels"; then
  node_xml='<Relationship Id="rIdCustomUI14" Type="http://schemas.microsoft.com/office/2007/relationships/ui/extensibility" Target="customUI/customUI14.xml"/>'
  # insert before the closing tag without touching anything else
  python3 - "$rels" "$node_xml" <<'PY'
import sys
p, node = sys.argv[1], sys.argv[2]
s = open(p, encoding="utf-8").read()
s = s.replace("</Relationships>", node + "</Relationships>", 1)
open(p, "w", encoding="utf-8").write(s)
PY
fi

cp "$pkg" "$pkg.bak"
rm -f "$pkg"
( cd "$work" && zip -X -r -q "$pkg" '[Content_Types].xml' . )
echo "ribbon injected into $pkg  (backup: $pkg.bak)"
