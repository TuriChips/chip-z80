// tb: runs every case listed in tests/z80_bus/vectors/cases.txt (written by tests/z80_bus/cases.py; "<id> <halves> <stim events>" per line)
// against the DUT inside z80_system, prints one line per case and PASS / FAIL at the end (the toolchain's tb convention). Run from the repo root.
/* verilator lint_off UNUSEDSIGNAL */
module tb;
  z80_system sys ();
  integer fd, n, nh, nev, rc, total, mutate;
  string name, cases, vroot;
  initial begin
    total = 0;
    if ($value$plusargs("MUTATE=%d", mutate)) begin sys.mutate_half = mutate; sys.mutate_bit = 11; end   // MOCK only: flip m1_n in that half
    vroot = "tests/z80_bus/vectors/";
    void'($value$plusargs("VECROOT=%s", vroot));
    cases = {vroot, "cases.txt"};
    void'($value$plusargs("CASES=%s", cases));
    fd = $fopen(cases, "r");
    if (fd == 0) begin $display("FAIL cannot open %0s (run tests/z80_bus/cases.py)", cases); $finish; end
    while (!$feof(fd)) begin
      rc = $fscanf(fd, "%s %d %d\n", name, nh, nev);
      if (rc == 3) begin
        sys.run_case(name, nh, nev);
        total = total + 1;
      end
    end
    $fclose(fd);
    if (sys.errors == 0 && total > 0) $display("PASS %0d cases", total);
    else $display("FAIL %0d cases, %0d half-state mismatches", total, sys.errors);
    $finish;
  end
endmodule
