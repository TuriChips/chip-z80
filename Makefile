# Bump TOOLCHAIN_REF on purpose, never track main. Bump the @tag in .github/workflows/*.yml with it.
TOOLCHAIN_REF ?= v0.10.2
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

# C8 random programs vs the reference model, DUT = the RTL (spec §7 C8; tests/random/run.sh with scripts/rtl_trace.sh).
# Small by default (not in ci.yml, which is the toolchain's reusable workflow); full run is the nightly's: make c8-rtl SEEDS=64 INSTR=1000 (via `heavy` locally).
# Logs in C8_RUN (default logs/c8-rtl): random-c8.log has one line per seed, random-c8-coverage.log the coverage.
SEEDS ?= 8
INSTR ?= 300
C8_RUN ?= logs/c8-rtl
# Coverage (every form executed) needs the full run, so with few seeds it is printed but does not fail the target;
# any other FAIL (selftests, xchecks, a seed that differs) always does. Enforce it: C8_COVER=1 (default 1 when SEEDS>=64).
C8_COVER ?= $(shell [ $(SEEDS) -ge 64 ] && echo 1 || echo 0)
.PHONY: c8-rtl
c8-rtl:
	@mkdir -p $(C8_RUN); : >$(C8_RUN)/summary.txt; \
	{ RUN_DIR=$(C8_RUN) SEEDS=$(SEEDS) INSTR=$(INSTR) DUT=rtl RTL_TRACE_CMD=scripts/rtl_trace.sh tests/random/run.sh; echo $$? >$(C8_RUN)/rc; } | tee $(C8_RUN)/summary.txt; \
	rc=$$(cat $(C8_RUN)/rc 2>/dev/null || echo missing); S=$(C8_RUN)/summary.txt; \
	bad=$$(grep '^FAIL' $$S | grep -v -e '^FAIL coverage' -e '^FAIL random' || true); \
	if [ -n "$$bad" ]; then echo "c8-rtl: FAIL"; exit 1; fi; \
	grep -q "^C8 (DUT=rtl): $(SEEDS)/$(SEEDS) seeds pass" $$S && grep -q '^PASS c8' $(C8_RUN)/random-c8.log || { echo "c8-rtl: FAIL (no positive evidence that all $(SEEDS) seeds passed; run.sh rc=$$rc)"; exit 1; }; \
	grep -q -e '^PASS coverage' -e '^FAIL coverage' $$S || { echo "c8-rtl: FAIL (no coverage line; run.sh rc=$$rc)"; exit 1; }; \
	if [ "$$rc" != 0 ] && ! grep -q '^FAIL coverage' $$S; then echo "c8-rtl: FAIL (run.sh rc=$$rc)"; exit 1; fi; \
	if [ "$(C8_COVER)" = 1 ] && { [ "$$rc" != 0 ] || grep -q '^FAIL coverage' $$S; }; then echo "c8-rtl: FAIL (coverage)"; exit 1; fi; \
	echo "c8-rtl: PASS (C8 on the RTL, $(SEEDS) seeds x $(INSTR) instructions; coverage enforced: $(C8_COVER))"

# Fast acceptance driver (chip-z80#72): same interface as sw/exerciser/z80_acc_tb.sv, C++ clock loop, no --timing.
# Binary: build/acc-fast/obj/Vz80_system, run as: build/acc-fast/obj/Vz80_system +hex=<file> +maxclk=<n>
ACC_FAST_OBJ := build/acc-fast/obj
.PHONY: acc-fast-build
acc-fast-build:
	@mkdir -p $(ACC_FAST_OBJ)
	verilator --cc --exe --build -Wno-fatal -O3 --x-assign fast --x-initial fast -CFLAGS "-O3 -march=native" -j 2 -Irtl/control \
	  --top-module z80_system -GCPM=1 --public-flat-rw -Mdir $(ACC_FAST_OBJ) \
	  rtl/datapath/z80_alu.v rtl/datapath/z80_regs.v rtl/control/z80_timing.v rtl/control/z80_decode.v rtl/control/z80_control.v \
	  rtl/top.v rtl/datapath/z80_mem.v rtl/control/z80_system.v $(CURDIR)/scripts/acc_fast.cpp >$(ACC_FAST_OBJ)/build.log 2>&1 \
	  || { tail -20 $(ACC_FAST_OBJ)/build.log; exit 1; }
	@echo "built $(ACC_FAST_OBJ)/Vz80_system"
