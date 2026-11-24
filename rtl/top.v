// z80: the CPU top level. Pins of spec section 2, ports of docs/blocks.md section 3 (z80).
// Wiring of z80_timing, z80_control, z80_alu, z80_regs, plus the ALU operand muxes (blocks 2.3: alu_a_sel,
// alu_b_sel) and the data-out mux (blocks 2.4: d_out_sel). z80_decode sits inside z80_control (ports between
// Zura's own blocks, blocks.md section 1).
/* verilator lint_off DECLFILENAME */
module z80 (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        wait_n,
    input  wire        int_n,
    input  wire        nmi_n,
    input  wire        busrq_n,
    input  wire [7:0]  d_in,
    output wire [15:0] a,
    output wire [7:0]  d_out,
    output wire        d_oe,
    output wire        bus_oe,
    output wire        m1_n,
    output wire        mreq_n,
    output wire        iorq_n,
    output wire        rd_n,
    output wire        wr_n,
    output wire        rfsh_n,
    output wire        halt_n,
    output wire        busak_n
);
    wire reset = ~reset_n;

    // timing <-> control
    wire [2:0] t, mc_type, mc_len;
    wire       tw, ph, tx, d_strobe, samp_last, mc_end, rfsh, r_inc;
    // control -> datapath
    wire [2:0] addr_sel, pair_sel, pair_op, pc_op, wz_op, bit_n, d_out_sel, alu_b_sel;
    wire [1:0] sp_op, alu_a_sel;
    wire [3:0] rd_a_sel, rd_b_sel, wr_sel;
    wire [5:0] alu_op;
    wire [7:0] rst_vec, tmp;
    wire       wr_we, a_we, f_we, f_load, af_swap, iff2;
    // datapath -> control / muxes
    wire [7:0] rd_a, rd_b, a_out, f_out, result;
    wire       bc_nz, b_nz;
    wire [15:0] pc_dbg;

    z80_timing u_timing (
        .clk(clk), .reset(reset), .wait_n(wait_n), .busrq_n(busrq_n),
        .mc_type(mc_type), .mc_len(mc_len),
        .t(t), .tw(tw), .ph(ph), .tx(tx), .d_strobe(d_strobe), .samp_last(samp_last), .mc_end(mc_end),
        .rfsh(rfsh), .r_inc(r_inc),
        .m1_n(m1_n), .mreq_n(mreq_n), .iorq_n(iorq_n), .rd_n(rd_n), .wr_n(wr_n), .rfsh_n(rfsh_n),
        .d_oe(d_oe), .bus_oe(bus_oe), .busak_n(busak_n)
    );

    z80_control u_control (
        .clk(clk), .reset(reset), .d_in(d_in),
        .int_n(int_n), .nmi_n(nmi_n), .busrq_n(busrq_n),
        .t(t), .tw(tw), .ph(ph), .tx(tx), .d_strobe(d_strobe), .samp_last(samp_last), .mc_end(mc_end),
        .f_out(f_out), .result(result), .bc_nz(bc_nz), .b_nz(b_nz),
        .mc_type(mc_type), .mc_len(mc_len),
        .addr_sel(addr_sel), .rd_a_sel(rd_a_sel), .rd_b_sel(rd_b_sel), .wr_sel(wr_sel), .wr_we(wr_we),
        .pair_sel(pair_sel), .pair_op(pair_op), .pc_op(pc_op), .sp_op(sp_op), .wz_op(wz_op),
        .rst_vec(rst_vec),
        .alu_op(alu_op), .alu_a_sel(alu_a_sel), .alu_b_sel(alu_b_sel), .a_we(a_we), .f_we(f_we),
        .f_load(f_load), .af_swap(af_swap), .bit_n(bit_n), .iff2(iff2),
        .d_out_sel(d_out_sel), .tmp(tmp), .halt_n(halt_n)
    );

    // ALU operand muxes (blocks 2.3)
    reg [7:0] alu_a_in, alu_b_in;
    always @* begin
        case (alu_a_sel)
            2'd0:    alu_a_in = a_out;
            2'd1:    alu_a_in = rd_a;
            default: alu_a_in = 8'h00;
        endcase
        case (alu_b_sel)
            3'd0:    alu_b_in = d_in;
            3'd1:    alu_b_in = tmp;
            3'd2:    alu_b_in = rd_b;
            3'd3:    alu_b_in = a_out;
            default: alu_b_in = 8'h00;
        endcase
    end

    z80_alu u_alu (
        .clk(clk), .reset(reset), .op(alu_op), .a_in(alu_a_in), .b(alu_b_in),
        .a_we(a_we), .f_we(f_we), .f_load(f_load), .af_swap(af_swap), .bit_n(bit_n),
        .iff2(iff2), .bc_nz(bc_nz), .a_out(a_out), .f_out(f_out), .result(result)
    );

    z80_regs u_regs (
        .clk(clk), .reset(reset), .d_in(d_in), .wdata(result), .wr_sel(wr_sel), .wr_we(wr_we),
        .rd_a_sel(rd_a_sel), .rd_b_sel(rd_b_sel), .pair_sel(pair_sel), .pair_op(pair_op),
        .pc_op(pc_op), .sp_op(sp_op), .wz_op(wz_op), .rst_vec(rst_vec), .a_val(a_out),
        .addr_sel(addr_sel), .rfsh(rfsh), .r_inc(r_inc),
        .rd_a(rd_a), .rd_b(rd_b), .addr(a), .bc_nz(bc_nz), .b_nz(b_nz), .pc(pc_dbg)
    );

    // data-out mux (blocks 2.4)
    reg [7:0] d_out_r;
    always @* begin
        case (d_out_sel)
            3'd0:    d_out_r = a_out;
            3'd1:    d_out_r = f_out;
            3'd2:    d_out_r = rd_b;
            default: d_out_r = tmp;
        endcase
    end
    assign d_out = d_out_r;

    wire unused_ok = &{1'b0, pc_dbg};
endmodule
