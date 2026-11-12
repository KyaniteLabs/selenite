#!/usr/bin/env python3
"""Embed desktop/fonts/*.woff into desktop/plugin.js between the FONTS markers.

Desktop plugins may import only the SDK and React, so the Chakra Petch subset
ships inline as base64. Rebuild the subset with:
  pyftsubset ChakraPetch-<W>.ttf --flavor=woff --output-file=desktop/fonts/cp-<W>.woff \
    --unicodes="U+0020-007E,U+00A0-00FF,U+2013-2014,U+2018-201D,U+2022,U+2026,U+2190-2193,U+00D7,U+2212" \
    --layout-features='kern,liga'
Chakra Petch ships no tnum feature, so its digits stay proportional; the plugin
puts aligned counts in the host mono face instead.
"""
import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = {"Medium": 500, "SemiBold": 600}

entries = []
for name, weight in WEIGHTS.items():
    b64 = base64.b64encode((ROOT / "desktop/fonts" / f"cp-{name}.woff").read_bytes()).decode()
    entries.append(f"  {weight}: '{b64}'")
block = "const FONTS = {\n" + ",\n".join(entries) + "\n}"

js = ROOT / "desktop/plugin.js"
src = js.read_text(encoding="utf-8")
new, n = re.subn(r"(// --- FONTS \(generated\) -+\n).*?(\n// --- /FONTS)", lambda m: m.group(1) + block + m.group(2), src, flags=re.S)
if n != 1:
    raise SystemExit("FONTS markers not found")
js.write_text(new)
print(f"embedded {len(entries)} weights, plugin.js is {len(new) // 1024} KB")
