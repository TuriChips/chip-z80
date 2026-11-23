// z80_system: the Z80 test system (spec §7). One DUT, 64 KiB RAM, an I/O port model, input stimulus replayed from a vector file,
// and a pin recorder/comparator that looks at every pin of §2 in every half T state (§4.0: one model clock edge per half).
//
// Top module name: one macro. The name is still being settled (Makefile z80_top vs blocks.md z80, see the spec-v1 issue):
//   build with +define+Z80_TOP=z80 (default z80, as the Makefile TOP since chip-z80#16)
// Ports are the §2 names exactly: clk reset_n wait_n int_n nmi_n busrq_n d_in | a d_out d_oe m1_n mreq_n iorq_n rd_n wr_n rfsh_n
// halt_n busak_n bus_oe.
//
// Per case (tests/z80_bus/vectors/<id>/): prog.hex (+ prog<k>.hex reloaded at a stimulus event's bank field), stim.hex (32-bit words
// {h[23:0], bank[1:0], reset_n, nmi_n, busrq... see below}), exp.hex / mask.hex (36-bit expected pin vector and compare mask per half).
//   stim word: [31:8] h = half index the new input values start at; [7] 0; [6:5] bank (0 = none); [4] reset_n; [3] nmi_n; [2] int_n;
//              [1] busrq_n; [0] wait_n. All inputs take their new value at the edge that starts half h and are seen by samples after it
//              (§8.4 general rule). Before the first edge: reset_n = 0, everything else 1.
//   vector, 36 bits: [35:20] a  [19:12] d_out  [11] m1_n [10] mreq_n [9] iorq_n [8] rd_n [7] wr_n [6] rfsh_n [5] halt_n [4] busak_n
//              [3] bus_oe [2] d_oe [1:0] 0. A mask bit of 0 = not compared (floating pins, don't-cares of the spec).
// Environment: IN data = port[7:0] ^ A5H. INTA data (m1_n = iorq_n = 0) = FFH (RST 38H).
`ifndef Z80_TOP
`define Z80_TOP z80
`endif
/* verilator lint_off UNUSEDSIGNAL */
/* verilator lint_off UNDRIVEN */
/* verilator lint_off BLKSEQ */
/* verilator lint_off WIDTHEXPAND */
/* verilator lint_off WIDTHTRUNC */
/* verilator lint_off WIDTHCONCAT */
module z80_system;
  localparam MAXH = 8192;
  reg clk = 1'b0;
  reg reset_n = 1'b0, wait_n = 1'b1, int_n = 1'b1, nmi_n = 1'b1, busrq_n = 1'b1;
  wire [15:0] a;
  wire [7:0] d_in, d_out;
  wire d_oe, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_oe;

  reg [7:0] mem [0:65535];
  reg [35:0] exp [0:MAXH-1];
  reg [35:0] msk [0:MAXH-1];
  reg [31:0] ev [0:MAXH-1];
  reg [4:0] inp [0:MAXH-1];

  string case_dir, case_name;
  integer hc, nev, ev_i, nh, errors, case_errors, i;
  reg active = 1'b0;
  integer trace_fd = 0;
  string trace_file;
  integer mutate_half = -1, mutate_bit = 0;

  always #5 clk = ~clk;

`ifdef Z80_MOCK
  // Harness self-test only: replay the expected vector as if it were a perfect DUT (checks loader, compare and mask plumbing).
  reg [15:0] m_a; reg [7:0] m_d; reg m_m1, m_mreq, m_iorq, m_rd, m_wr, m_rfsh, m_halt, m_busak, m_oe, m_doe;
  assign a = m_a; assign d_out = m_d; assign d_oe = m_doe; assign m1_n = m_m1; assign mreq_n = m_mreq; assign iorq_n = m_iorq;
  assign rd_n = m_rd; assign wr_n = m_wr; assign rfsh_n = m_rfsh; assign halt_n = m_halt; assign busak_n = m_busak; assign bus_oe = m_oe;
  always @(clk) if (active && hc >= 0 && hc < nh) begin : mock
    reg [35:0] v;
    v = exp[hc];
    if (hc == mutate_half) v[mutate_bit] = ~v[mutate_bit];
    {m_a, m_d, m_m1, m_mreq, m_iorq, m_rd, m_wr, m_rfsh, m_halt, m_busak, m_oe, m_doe} <= v[35:2];
  end
`else
  `Z80_TOP dut (.clk(clk), .reset_n(reset_n), .wait_n(wait_n), .int_n(int_n), .nmi_n(nmi_n), .busrq_n(busrq_n),
                .a(a), .d_in(d_in), .d_out(d_out), .d_oe(d_oe), .m1_n(m1_n), .mreq_n(mreq_n), .iorq_n(iorq_n),
                .rd_n(rd_n), .wr_n(wr_n), .rfsh_n(rfsh_n), .halt_n(halt_n), .busak_n(busak_n), .bus_oe(bus_oe));
`endif

  // memory, I/O and interrupt-acknowledge data
  wire inta = (m1_n === 1'b0) && (iorq_n === 1'b0);
  assign d_in = inta ? 8'hFF : (iorq_n === 1'b0) ? (a[7:0] ^ 8'hA5) : mem[a];

  // load a case, with the model clock stopped at a falling edge so the next edge is the rising edge that starts half 0
  task load_case(input string name, input integer nhalves, input integer nevents);
    begin
      case_name = name;
      case_dir = {"tests/z80_bus/vectors/", name};
      nh = nhalves; nev = nevents;
      for (i = 0; i < 65536; i = i + 1) mem[i] = 8'h00;
      $readmemh({case_dir, "/prog.hex"}, mem);
      $readmemh({case_dir, "/stim.hex"}, ev, 0, nevents - 1);
      $readmemh({case_dir, "/exp.hex"}, exp, 0, nhalves - 1);
      $readmemh({case_dir, "/mask.hex"}, msk, 0, nhalves - 1);
      $readmemh({case_dir, "/inp.hex"}, inp, 0, nhalves - 1);
      reset_n = 1'b0; wait_n = 1'b1; int_n = 1'b1; nmi_n = 1'b1; busrq_n = 1'b1;
      hc = -1; ev_i = 0; case_errors = 0;
      if ($value$plusargs("TRACE=%s", trace_file)) begin
        trace_fd = $fopen({trace_file, ".", name, ".txt"}, "w");
        $fdisplay(trace_fd, "half a d_out d_oe m1_n mreq_n iorq_n rd_n wr_n rfsh_n halt_n busak_n bus_oe | wait_n int_n nmi_n busrq_n reset_n d_in");
      end
      active = 1'b1;
    end
  endtask

  task run_case(input string name, input integer nhalves, input integer nevents);
    begin
      @(negedge clk);
      load_case(name, nhalves, nevents);
      wait (!active);
      errors = errors + case_errors;
      $display("%s %s: %0d halves, %0d errors", case_errors == 0 ? "ok  " : "FAIL", name, nhalves, case_errors);
    end
  endtask

  // one model edge = one half T state. Inputs change here (non-blocking, so this edge's own samples see the old value), outputs are
  // read 4 ns later, just before the next edge: the value each pin holds through the half.
  always @(clk) begin : half
    reg [35:0] act;
    if (active) begin
      hc = hc + 1;
      if (ev_i < nev && ev[ev_i][31:8] == hc) begin
        wait_n <= ev[ev_i][0]; busrq_n <= ev[ev_i][1]; int_n <= ev[ev_i][2]; nmi_n <= ev[ev_i][3]; reset_n <= ev[ev_i][4];
        if (ev[ev_i][6:5] != 2'b00) $readmemh({case_dir, "/prog", 8'h30 + {6'b0, ev[ev_i][6:5]}, ".hex"}, mem);
        ev_i = ev_i + 1;
      end
      #4;
      if (mreq_n === 1'b0 && wr_n === 1'b0 && d_oe === 1'b1 && bus_oe === 1'b1) mem[a] = d_out;
      act = {a, d_out, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_oe, d_oe, 2'b00};
      if (trace_fd != 0)
        $fdisplay(trace_fd, "%0d %h %h %b %b %b %b %b %b %b %b %b %b | %b %b %b %b %b %h", hc, a, d_out, d_oe, m1_n, mreq_n, iorq_n, rd_n,
                  wr_n, rfsh_n, halt_n, busak_n, bus_oe, wait_n, int_n, nmi_n, busrq_n, reset_n, d_in);
      if (((act ^ exp[hc]) & msk[hc]) !== 36'b0) begin
        case_errors = case_errors + 1;
        if (case_errors <= 5)
          $display("FAIL %s half %0d: got %09h expected %09h mask %09h (a d_out m1 mreq iorq rd wr rfsh halt busak bus_oe d_oe)",
                   case_name, hc, act, exp[hc], msk[hc]);
      end
      if ({reset_n, nmi_n, int_n, busrq_n, wait_n} !== inp[hc]) begin
        case_errors = case_errors + 1;
        if (case_errors <= 5) $display("FAIL %s half %0d: stimulus {reset nmi int busrq wait} = %b, expected %b (harness bug)", case_name, hc,
                                       {reset_n, nmi_n, int_n, busrq_n, wait_n}, inp[hc]);
      end
      if (hc == nh - 1) begin
        active = 1'b0;
        if (trace_fd != 0) begin $fclose(trace_fd); trace_fd = 0; end
      end
    end
  end

  initial errors = 0;
endmodule
