// Homer's acceptance bench (sw/exerciser/run_rtl.sh): z80_system CPM=1 running one CP/M .COM, memory loaded from a hex file.
// Plusargs: +hex=<file> ($readmemh into the 64 KiB RAM, '@0100' first)  +maxclk=<half-clock limit, default 4e9>
// Prints con_char on con_strobe. At the end prints one '[acc]' line: done, sticky bus_conflict (seen on any half-clock), half-clock count. Not a test (the .COM judges).
module z80_acc_tb;
    reg clk = 0, reset_n = 0;
    wire [15:0] a; wire [7:0] d_out, con_char;
    wire d_oe, bus_oe, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_conflict, con_strobe, done;
    z80_system #(.MEM_INIT(""), .IO_INIT(""), .CPM(1)) dut (
        .clk(clk), .reset_n(reset_n), .wait_n(1'b1), .int_n(1'b1), .nmi_n(1'b1), .busrq_n(1'b1), .int_vector(8'h00),
        .a(a), .d_out(d_out), .d_oe(d_oe), .bus_oe(bus_oe), .m1_n(m1_n), .mreq_n(mreq_n), .iorq_n(iorq_n),
        .rd_n(rd_n), .wr_n(wr_n), .rfsh_n(rfsh_n), .halt_n(halt_n), .busak_n(busak_n),
        .bus_conflict(bus_conflict), .con_char(con_char), .con_strobe(con_strobe), .done(done));
    always #1 clk = ~clk;
    reg [1023:0] hexf;
    longint unsigned n = 0, maxclk = 64'd4000000000;
    reg timed_out = 0, conflict_seen = 0;
    always @(posedge clk) begin
        if (con_strobe) $write("%c", con_char);
        if (bus_conflict) conflict_seen <= 1;
        n <= n + 1;
        if (done || n >= maxclk) begin
            if (!done) timed_out = 1;
            $display("\n[acc] done=%0d timeout=%0d bus_conflict=%0d half-T-clocks=%0d", done, timed_out, conflict_seen | bus_conflict, n);
            $finish;
        end
    end
    initial begin
        if (!$value$plusargs("hex=%s", hexf)) begin $display("[acc] need +hex=<file>"); $finish; end
        void'($value$plusargs("maxclk=%d", maxclk));
        #1 $readmemh(hexf, dut.u_mem.mem);
        repeat (8) @(posedge clk); reset_n = 1;
    end
endmodule
