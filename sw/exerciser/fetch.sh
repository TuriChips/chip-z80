#!/usr/bin/env bash
# Usage: sw/exerciser/fetch.sh [zexdoc|prelim|zexdoc-src|prelim-src|all]   (default: all binaries)
# Fetches the Z80 acceptance programs into build/third_party/ at test time, pinned by commit AND sha256.
# Never committed (rule 9: they are GPL-2.0 third-party code). Prints one path per file fetched.
# Built on scripts/fetch_thirdparty.sh (Tesla), which verifies the hash and caches. See sw/exerciser/README.md.
set -eu
cd "$(git rev-parse --show-toplevel)"
fetch=scripts/fetch_thirdparty.sh

ZEXALL=8f71d418bae69a476a5a0e5c6e122c8801b8d9f4   # agn453/ZEXALL  (prebuilt zexdoc.com)
YAZE=993d8647eabf95c61e49b134198a240ab577358b     # begoon/yaze    (prebuilt prelim.com, original sources)
EXER=8634cccdd362e030efebcdeec1aeb8b4f2ce9179     # begoon/z80exer (original yaze sources)

get() { # name url sha
  "$fetch" "$@"
}
case "${1:-all}" in
  zexdoc|all)
    get zexdoc.com "https://raw.githubusercontent.com/agn453/ZEXALL/$ZEXALL/zexdoc.com" \
        34923a7ed82285d3038b2d54bd64899e12173eebb61f9d07b4fc72e78af2ae8f ;;&
  prelim|all)
    get prelim.com "https://raw.githubusercontent.com/begoon/yaze/$YAZE/test/prelim.com" \
        3b3578f19030a4df7e25ce852f763af26053b12582a576c4dffb014aa7c590d1 ;;&
  zexdoc-src)
    get zexdoc.z80 "https://raw.githubusercontent.com/begoon/z80exer/$EXER/yaze/zexdoc.z80" \
        f82ccdea9ca0076aff11eac6d021276e2290344cd0e50e1353d5d1e46a981ef3 ;;&
  prelim-src)
    get prelim.z80 "https://raw.githubusercontent.com/begoon/z80exer/$EXER/yaze/prelim.z80" \
        afefdd15c42ea8d0c123ad099108962ca5ad26b3ffd043d2ba578c2b01cab1fd ;;&
  zexdoc|prelim|all|zexdoc-src|prelim-src) ;;
  *) echo "usage: $0 [zexdoc|prelim|zexdoc-src|prelim-src|all]" >&2; exit 2 ;;
esac
