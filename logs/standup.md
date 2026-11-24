
## 2026-11-23 Titus
- Passed: harness self-test with replay DUT, 48 cases (logs/z80-bus-harness-selftest.log); ref cross-check, 48 cases, 0 disagreements (logs/z80-bus-crosscheck.log). No RTL tests run.
- In progress: wait for Zura's top, then run tb/z80_bus on RTL (chip-z80#12 draft).
- Blocked: nothing; spec gaps in #11 for Igris.

## Titus 2026-11-24
- Passed: z80_bus 48/48 on RTL at main (290bb6f), logs/z80-bus-rtl.log
- In progress: waiting for CI and merge of PR #12
- Blocked: nothing
