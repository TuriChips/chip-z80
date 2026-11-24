// Zura's private smoke bench for z80_system (not a test, rule 3): runs a CP/M .COM (hex file at 0100H) to `done`,
// prints con_char on con_strobe, reports bus_conflict and done. Usage: see logs/z80_system-smoke.log header.
module z80_system_smoke;
    reg clk = 0, reset_n = 0;
    wire [15:0] a; wire [7:0] d_out, con_char;
    wire d_oe, bus_oe, m1_n, mreq_n, iorq_n, rd_n, wr_n, rfsh_n, halt_n, busak_n, bus_conflict, con_strobe, done;
    z80_system #(.MEM_INIT(`MEMF), .IO_INIT(""), .CPM(1)) dut (
        .clk(clk), .reset_n(reset_n), .wait_n(1'b1), .int_n(1'b1), .nmi_n(1'b1), .busrq_n(1'b1), .int_vector(8'h00),
        .a(a), .d_out(d_out), .d_oe(d_oe), .bus_oe(bus_oe), .m1_n(m1_n), .mreq_n(mreq_n), .iorq_n(iorq_n),
        .rd_n(rd_n), .wr_n(wr_n), .rfsh_n(rfsh_n), .halt_n(halt_n), .busak_n(busak_n),
        .bus_conflict(bus_conflict), .con_char(con_char), .con_strobe(con_strobe), .done(done));
    always #1 clk = ~clk;
    integer n = 0;
    always @(posedge clk) begin
        if (con_strobe) $write("%c", con_char);
        n <= n + 1;
        if (done || n > 200000000) begin
            $display("\n[smoke] done=%0d bus_conflict=%0d half-T-clocks=%0d", done, bus_conflict, n);
            $finish;
        end
    end
    initial begin repeat (8) @(posedge clk); reset_n = 1; end
endmodule
