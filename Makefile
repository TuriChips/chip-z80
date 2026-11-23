# Bump TOOLCHAIN_REF on purpose, never track main. Bump the @tag in .github/workflows/*.yml with it.
TOOLCHAIN_REF ?= v0.9
TOP ?= z80_top
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

# Long acceptance tests only (zexdoc); build/test/synth already run in PR CI. Skips cleanly until tests/acceptance/run.sh exists.
.PHONY: nightly
nightly:
	@scripts/nightly.sh
