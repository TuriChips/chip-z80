Issue #101, spec §3 ruling 6 (a). C8 on the RTL (rtl_trace.sh), 64 seeds x 1000 instructions, model policy x6='mostek', the 9 decision-6 forms back in (gen.EXCLUDED empty).
Result: 64/64 seeds pass, 0 pin differences, coverage PASS over all 850 forms. The 9 forms ran: ED A0 15, A1 46, A8 16, A9 15, B0 7378, B1 2812, B8 2530, B9 1808, main 3F 26 (see random-c8-coverage.log).
So CPI/CPD(R)'s 4th-cycle IO(5) (§3 A4) and LDI/LDD(R)'s MW(5) write are now pin-checked, not only decode-layout checked.
