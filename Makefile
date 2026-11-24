# Bump TOOLCHAIN_REF on purpose, never track main. Bump the @tag in .github/workflows/*.yml with it.
TOOLCHAIN_REF ?= v0.9
TOP ?= z80
TC := .toolchain
ifeq (,$(wildcard $(TC)/chip.mk))
$(shell rm -rf $(TC); gh repo clone TuriChips/toolchain $(TC) -- -q --depth 1 --branch $(TOOLCHAIN_REF))
endif
ifneq (,$(TOOLCHAIN_REF))
ifeq (,$(filter $(TOOLCHAIN_REF),$(shell git -C $(TC) tag --points-at HEAD 2>/dev/null)))
$(error toolchain mismatch: Makefile pins $(TOOLCHAIN_REF) but $(TC) is a different version. Run: rm -rf $(TC))
endif
endif
export TOP
include $(TC)/chip.mk

# Long acceptance tests only (zexdoc); build/test/synth already run in PR CI. Calls make acceptance; skips cleanly until sw/exerciser/run_rtl.py exists.
.PHONY: nightly
nightly:
	@scripts/nightly.sh

# Z80 exerciser acceptance on the RTL: prelim (seconds), then zexdoc (hours on 2 cores; nightly/manual, not PR CI).
# Writes logs/acc-rtl/{prelim,zexdoc}.log; non-zero exit if anything is not OK. Subset: make acceptance ACC_ARGS="--groups 0,1 --jobs 2"
# Needs verilator 5.020 and curl (sw/exerciser/fetch.sh).
.PHONY: acceptance
acceptance:
	@if [ -f sw/exerciser/run_rtl.py ]; then \
	  python3 -I sw/exerciser/run_rtl.py prelim && python3 -I sw/exerciser/run_rtl.py zexdoc $(ACC_ARGS); \
	else echo "SKIP acceptance: sw/exerciser/run_rtl.py not there yet (#55)"; fi
