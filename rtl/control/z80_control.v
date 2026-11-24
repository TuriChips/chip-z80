// z80_control: IR, prefix state, cycle-plan step, TMP, IFF1/IFF2, IM, NMI edge latch, EI delay, HALT state, and the
// per-instruction micro-operations. Ports: docs/blocks.md section 3 (z80_control), codes: section 2.
// z80_decode is instantiated here (ports between Zura's own blocks, blocks.md section 1): control gives it
// {prefix, ir} and gets the plan rows back.
//
// How an instruction runs. m = index of the current M cycle in the decode plan (the plan covers the whole
// instruction, prefix fetches included, see gen_decode.py). k = m - (number of prefix fetches) = the cycle
// counted from the opcode byte: k0 is the opcode fetch (for DD CB d op: the op-byte read). Every operation
// is asserted in ONE half (blocks.md section 1, timing rule): ST = d_strobe (the half that ends where d_in is
// taken), LST = mc_end (the last half of the M cycle), H3 = T3H (the first half in which the opcode just
// fetched is in IR), T1H / T3L / T4L = fixed halves for the few multi-step internal operations. Anything that
// changes the register behind `a` waits for LST, so `a` is stable for the whole cycle (spec 4.1-4.3).
module z80_control (
    input  wire       clk,
    input  wire       reset,
    input  wire [7:0] d_in,
    input  wire       int_n,
    input  wire       nmi_n,
    input  wire       busrq_n,
    input  wire [2:0] t,
    input  wire       tw,
    input  wire       ph,
    input  wire       tx,
    input  wire       d_strobe,
    input  wire       samp_last,
    input  wire       mc_end,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [7:0] f_out,      // only S, Z, P/V and C are used (conditions)
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire [7:0] result,
    input  wire       bc_nz,
    input  wire       b_nz,
    output reg  [2:0] mc_type,
    output reg  [2:0] mc_len,
    output reg  [2:0] addr_sel,
    output reg  [3:0] rd_a_sel,
    output reg  [3:0] rd_b_sel,
    output reg  [3:0] wr_sel,
    output reg        wr_we,
    output reg  [2:0] pair_sel,
    output reg  [2:0] pair_op,
    output reg  [2:0] pc_op,
    output reg  [1:0] sp_op,
    output reg  [2:0] wz_op,
    output reg  [7:0] rst_vec,
    output reg  [5:0] alu_op,
    output reg  [1:0] alu_a_sel,
    output reg  [2:0] alu_b_sel,
    output reg        a_we,
    output reg        f_we,
    output reg        f_load,
    output reg        af_swap,
    output reg  [2:0] bit_n,
    output wire       iff2,
    output reg  [2:0] d_out_sel,
    output wire [7:0] tmp,
    output reg        halt_n
);
    `include "z80_decode_kinds.vh"

    localparam [2:0] OCF = 3'd0, MRD = 3'd1, MWR = 3'd2, PRD = 3'd3, PWR = 3'd4, IOC = 3'd5, INTA = 3'd6;
    // r8 codes (blocks 2.2)
    localparam [3:0] R_B = 4'd0, R_C = 4'd1, R_H = 4'd4, R_L = 4'd5, R_I = 4'd6, R_R = 4'd7,
                     R_PCH = 4'd14, R_PCL = 4'd15;

    // ---------------------------------------------------------------- state
    reg [7:0] ir;
    reg [2:0] prefix;      // blocks 2.7
    reg [2:0] m;           // M cycle index in the plan (or in the interrupt response)
    reg [2:0] irk;         // 0 none, 1 NMI, 2 INT mode 0, 3 INT mode 1, 4 INT mode 2 (response in progress)
    reg       iff1, iff2_r;
    reg [1:0] im;
    reg [7:0] tmp_r;
    reg       nmi_q, nmi_pend;
    reg       ei_cur;      // the current instruction is EI: INT is not accepted at its end (spec 8.4 item 5)
    reg       halt_st;     // the CPU is halted: every M1 is a halted M1 (spec 4.7)
    reg       gon, goi;    // interrupt accepted at this instruction's sampling point
    assign iff2 = iff2_r;
    assign tmp  = tmp_r;

    // ---------------------------------------------------------------- decode
    wire        specified, is_prefix, s3;
    wire [6:0]  ins;
    wire [2:0]  pn, pn_s;
    wire [17:0] plan_type, plan_len;
    z80_decode u_decode (
        .prefix(prefix), .ir(ir), .specified(specified), .is_prefix(is_prefix), .ins(ins),
        .pn(pn), .pn_s(pn_s), .s3(s3), .plan_type(plan_type), .plan_len(plan_len)
    );

    // ---------------------------------------------------------------- helpers
    function cc(input [2:0] c, input [3:0] f);   // f = {S, Z, P/V, C}   // conditions NZ Z NC C PO PE P M (blocks section 3)
        case (c)
            3'd0: cc = ~f[2];
            3'd1: cc =  f[2];
            3'd2: cc = ~f[0];
            3'd3: cc =  f[0];
            3'd4: cc = ~f[1];
            3'd5: cc =  f[1];
            3'd6: cc = ~f[3];
            default: cc = f[3];
        endcase
    endfunction

    wire [2:0] mo      = (prefix == 3'd0) ? 3'd0 : (prefix <= 3'd4) ? 3'd1 : 3'd3;
    wire [2:0] k       = m - mo;
    wire       ddcb_pre = (prefix == 3'd5 || prefix == 3'd6) && (m < 3'd4);   // d and op byte reads
    wire       ixd     = (prefix == 3'd2) || (prefix == 3'd5);              // DD (IX) rather than FD (IY)
    wire [2:0] ixp     = ixd ? 3'd3 : 3'd4;                                 // pair_sel of IX / IY
    wire [3:0] ix_hi   = ixd ? 4'd8 : 4'd10;                                // IXH / IYH (low byte = +1)
    wire [1:0] dd      = ir[5:4];
    wire [3:0] dd_hi   = (dd == 2'd0) ? 4'd0 : (dd == 2'd1) ? 4'd2 : (dd == 2'd2) ? 4'd4 : 4'd12;
    wire [2:0] src3    = ir[2:0];
    wire [2:0] dst3    = ir[5:3];
    // Decision 9 U1 (spec 6.0a): under DD/FD the 8-bit-register kinds name IXH/IXL (IYH/IYL) for r = 4, 5. Those kinds only
    // occur under DD/FD for the U1/U2 forms; LD r,(IX+d) and the like are other kinds and keep the real H and L.
    wire       half_k  = (prefix == 3'd2 || prefix == 3'd4) &&
                         (ins == `Z80K_LD_R_R || ins == `Z80K_LD_R_N || ins == `Z80K_INC_R || ins == `Z80K_DEC_R ||
                          ins == `Z80K_ALU_R);
    wire [3:0] src4    = (half_k && (src3 == 3'd4 || src3 == 3'd5)) ? (ix_hi + {3'b0, src3[0]}) : {1'b0, src3};
    wire [3:0] dst4    = (half_k && (dst3 == 3'd4 || dst3 == 3'd5)) ? (ix_hi + {3'b0, dst3[0]}) : {1'b0, dst3};
    wire       src_a   = (src3 == 3'd7);
    wire       dst_a   = (dst3 == 3'd7);
    wire       dn      = ir[3];             // block instruction direction: 0 inc, 1 dec

    wire [3:0] fcc = {f_out[7], f_out[6], f_out[2], f_out[0]};
    // does the full plan run (condition met / repeating)?
    reg go;
    always @* begin
        case (ins)
            `Z80K_DJNZ:                                  go = b_nz;
            `Z80K_JR_CC:                                 go = cc({1'b0, ir[4:3]}, fcc);
            `Z80K_RET_CC, `Z80K_CALL_CC, `Z80K_JP_CC:    go = cc(ir[5:3], fcc);
            `Z80K_LDIR, `Z80K_LDDR:                      go = bc_nz;
            `Z80K_CPIR, `Z80K_CPDR:                      go = bc_nz & ~f_out[6];
            `Z80K_INIR, `Z80K_INDR, `Z80K_OUTIR, `Z80K_OUTDR: go = b_nz;
            default:                                     go = 1'b1;
        endcase
    end

    wire resp     = (irk != 3'd0);
    wire [2:0] pn_e = go ? pn : pn_s;
    wire last_ins = !is_prefix && !ddcb_pre && ({1'b0, m} + 4'd1 >= {1'b0, pn_e});
    wire halted_m1 = halt_st && (m == 3'd0) && !resp;
    wire last_resp = (irk == 3'd4) ? (m == 3'd4) : (m == 3'd2);
    wire last_any  = resp ? last_resp : (halted_m1 | last_ins);

    // ---------------------------------------------------------------- half slots (never in a Tx or a Tw)
    wire ok   = !tx && !tw;
    wire ST   = d_strobe;
    wire LST  = mc_end;
    wire H3   = ok && !ph && (t == 3'd3);
    wire T1H  = ok && !ph && (t == 3'd1);
    wire T2H  = ok && !ph && (t == 3'd2);
    wire T3L  = ok &&  ph && (t == 3'd3);

    wire fetch_pc  = (mc_type == OCF) && !resp && !halt_st;     // an opcode fetch that advances PC
    wire ign_ocf   = (mc_type == OCF) && (resp || halt_st);     // NMI dummy fetch / halted M1: data ignored
    wire kind_en   = !resp && !ign_ocf && !ddcb_pre;
    wire ddcb_m3   = ddcb_pre && (m == 3'd3);
    wire ir_load   = ST && (fetch_pc || ddcb_m3 || (irk == 3'd2 && m == 3'd0));

    // ---------------------------------------------------------------- micro-operations
    reg        wd_go, wd_a;           // write result to register wd_r (or to A when wd_a), in this half
    reg [3:0]  wd_r;
    reg        tmp_we, tmp_res;       // TMP load: from d_in (0) or from the ALU result (1)
    reg        c_di, c_ei, c_retn, c_im, c_halt;
    reg        pcinc;                 // operand byte read: PC + 1 at LST

    always @* begin
        addr_sel = 3'd0; rd_a_sel = 4'd0; rd_b_sel = 4'd0; wr_sel = 4'd0; wr_we = 1'b0;
        pair_sel = 3'd0; pair_op = 3'd0; pc_op = 3'd0; sp_op = 2'd0; wz_op = 3'd0; rst_vec = ir & 8'h38;
        alu_op = 6'd0; alu_a_sel = 2'd0; alu_b_sel = 3'd0; a_we = 1'b0; f_we = 1'b0; f_load = 1'b0;
        af_swap = 1'b0; bit_n = ir[5:3]; d_out_sel = 3'd0;
        wd_go = 1'b0; wd_a = 1'b0; wd_r = 4'd0; tmp_we = 1'b0; tmp_res = 1'b0;
        c_di = 1'b0; c_ei = 1'b0; c_retn = 1'b0; c_im = 1'b0; c_halt = 1'b0; pcinc = 1'b0;

        if (resp) begin
            // ---- interrupt responses (spec 4.5, 4.6, 8.2). m0 INTA/OCF(5); m1 SWH; m2 SWL; mode 2: m3 MRL, m4 MRH
            rst_vec = (irk == 3'd1) ? 8'h66 : (irk == 3'd3) ? 8'h38 : (ir & 8'h38);
            case (m)
                3'd0: begin
                    // mode 0: IR <- vector (ir_load)
                    if (irk == 3'd4 && ST) wz_op = 3'd4;
                    if (LST) sp_op = 2'd1;
                end
                3'd1: begin
                    addr_sel = 3'd1; d_out_sel = 3'd2; rd_b_sel = R_PCH;
                    if (LST) sp_op = 2'd1;
                end
                3'd2: begin
                    addr_sel = 3'd1; d_out_sel = 3'd2; rd_b_sel = R_PCL;
                    if (LST && irk != 3'd4) pc_op = 3'd7;
                end
                3'd3: begin                       // mode 2: PCL <- (WZ)
                    addr_sel = 3'd2; alu_op = 6'd0; alu_b_sel = 3'd0;
                    wr_sel = R_PCL; wr_we = ST;
                    if (LST) wz_op = 3'd5;
                end
                default: begin                    // mode 2: PCH <- (WZ + 1)
                    addr_sel = 3'd2; alu_op = 6'd0; alu_b_sel = 3'd0;
                    wr_sel = R_PCH; wr_we = ST;
                end
            endcase
        end else if (ddcb_pre) begin
            // DD CB d op: m2 reads d (OD, 3 T), m3 reads the op byte into IR (5 T) and forms IX + d
            if (m == 3'd2) begin
                if (ST) wz_op = 3'd1;
                if (LST) pc_op = 3'd1;
            end else if (m == 3'd3) begin
                if (LST) begin pc_op = 3'd1; pair_op = 3'd6; pair_sel = ixp; end
            end
        end else if (fetch_pc && ST) begin
            pc_op = 3'd1;                         // PC + 1 at the edge that starts T3H
        end

        if (kind_en) begin
            case (ins)
            // ------------------------------------------------ 8-bit loads
            `Z80K_LD_R_N: if (k == 3'd1) begin
                alu_b_sel = 3'd0; wd_go = ST; wd_a = dst_a; wd_r = dst4; pcinc = 1'b1;
            end
            `Z80K_LD_R_R: if (k == 3'd0) begin
                wd_go = LST; wd_a = dst_a; wd_r = dst4;
                if (src_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_LD_R_HL: if (k == 3'd1) begin       // via TMP: LD H,(HL) must not move `a` before T3L ends
                addr_sel = 3'd5; alu_b_sel = 3'd1; tmp_we = ST; wd_go = LST; wd_a = dst_a; wd_r = dst4;
            end
            `Z80K_LD_HL_R: if (k == 3'd1) begin
                addr_sel = 3'd5;
                if (src_a) d_out_sel = 3'd0; else begin d_out_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_LD_HL_N: begin
                if (k == 3'd1) begin tmp_we = ST; pcinc = 1'b1; end
                if (k == 3'd2) begin addr_sel = 3'd5; d_out_sel = 3'd3; end
            end
            `Z80K_LD_RP_A: if (k == 3'd1) begin addr_sel = ir[4] ? 3'd4 : 3'd3; d_out_sel = 3'd0; end
            `Z80K_LD_A_RP: if (k == 3'd1) begin
                addr_sel = ir[4] ? 3'd4 : 3'd3; alu_b_sel = 3'd0; wd_go = ST; wd_a = 1'b1;
            end
            `Z80K_LD_NN_A, `Z80K_LD_A_NN: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2) begin wz_op = ST ? 3'd2 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd3) begin
                    addr_sel = 3'd2;
                    if (ins == `Z80K_LD_NN_A) d_out_sel = 3'd0;
                    else begin alu_b_sel = 3'd0; wd_go = ST; wd_a = 1'b1; end
                end
            end
            `Z80K_LD_A_I, `Z80K_LD_A_R: if (k == 3'd0) begin    // OCF(5): flags and A at the last half
                alu_op = 6'd33; alu_b_sel = 3'd2; rd_b_sel = ir[3] ? R_R : R_I;
                a_we = LST; f_we = LST;
            end
            `Z80K_LD_I_A, `Z80K_LD_R_A: if (k == 3'd0) begin
                alu_b_sel = 3'd3; wr_sel = ir[3] ? R_R : R_I; wr_we = LST;
            end

            // ------------------------------------------------ 16-bit loads
            `Z80K_LD_DD_NN, `Z80K_LD_IX_NN: begin
                if (k == 3'd1 || k == 3'd2) begin
                    alu_b_sel = 3'd0; wd_go = ST; pcinc = 1'b1;
                    wd_r = (ins == `Z80K_LD_IX_NN) ? (ix_hi + {3'b0, (k == 3'd1)}) :
                                                     (dd_hi + {3'b0, (k == 3'd1)});
                end
            end
            `Z80K_LD_NN_HL, `Z80K_LD_NN_DD, `Z80K_LD_NN_IX, `Z80K_LD_HL_NN, `Z80K_LD_DD_NN_IND, `Z80K_LD_IX_NNI: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2) begin wz_op = ST ? 3'd2 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd3 || k == 3'd4) begin
                    addr_sel = 3'd2;
                    if (k == 3'd3 && LST) wz_op = 3'd5;
                    case (ins)
                        `Z80K_LD_NN_HL, `Z80K_LD_HL_NN:         wd_r = R_H;
                        `Z80K_LD_NN_DD, `Z80K_LD_DD_NN_IND:     wd_r = dd_hi;
                        default:                                wd_r = ix_hi;
                    endcase
                    if (ins == `Z80K_LD_NN_HL || ins == `Z80K_LD_NN_DD || ins == `Z80K_LD_NN_IX) begin
                        d_out_sel = 3'd2; rd_b_sel = (k == 3'd3) ? (wd_r + 4'd1) : wd_r;
                    end else begin
                        alu_b_sel = 3'd0; wd_go = ST; wd_r = (k == 3'd3) ? (wd_r + 4'd1) : wd_r;
                    end
                end
            end
            `Z80K_LD_SP_HL: if (k == 3'd0 && LST) begin sp_op = 2'd3; pair_sel = 3'd2; end
            `Z80K_LD_SP_IX: if (k == 3'd0 && LST) begin sp_op = 2'd3; pair_sel = ixp; end
            `Z80K_PUSH, `Z80K_PUSH_IX: begin
                if (k == 3'd0 && LST) sp_op = 2'd1;
                if (k == 3'd1 || k == 3'd2) begin
                    addr_sel = 3'd1;
                    if (LST && k == 3'd1) sp_op = 2'd1;
                    if (ins == `Z80K_PUSH && dd == 2'd3) d_out_sel = (k == 3'd1) ? 3'd0 : 3'd1;
                    else begin
                        d_out_sel = 3'd2;
                        rd_b_sel = (ins == `Z80K_PUSH_IX) ? ix_hi : dd_hi;
                        if (k == 3'd2) rd_b_sel = rd_b_sel + 4'd1;
                    end
                end
            end
            `Z80K_POP, `Z80K_POP_IX: begin
                if (k == 3'd1 || k == 3'd2) begin
                    addr_sel = 3'd1; alu_b_sel = 3'd0;
                    if (LST) sp_op = 2'd2;
                    if (ins == `Z80K_POP && dd == 2'd3) begin
                        if (k == 3'd1) f_load = ST; else begin wd_go = ST; wd_a = 1'b1; end
                    end else begin
                        wd_go = ST;
                        wd_r = (ins == `Z80K_POP_IX) ? ix_hi : dd_hi;
                        if (k == 3'd1) wd_r = wd_r + 4'd1;
                    end
                end
            end

            // ------------------------------------------------ exchange
            `Z80K_EX_DE_HL: if (k == 3'd0 && LST) pair_op = 3'd3;
            `Z80K_EXX:      if (k == 3'd0 && LST) pair_op = 3'd4;
            `Z80K_EX_AF:    if (k == 3'd0 && LST) af_swap = 1'b1;
            `Z80K_EX_SP_HL, `Z80K_EX_SP_IX: begin
                // OCF, SRL at SP, SRH(4) at SP+1, SWH at SP+1, SWL(5) at SP; SP is stepped +1 after SRL, -1 after SWH
                if (k == 3'd1) begin addr_sel = 3'd1; wz_op = ST ? 3'd1 : 3'd0; if (LST) sp_op = 2'd2; end
                if (k == 3'd2) begin addr_sel = 3'd1; wz_op = ST ? 3'd2 : 3'd0; end
                if (k == 3'd3) begin
                    addr_sel = 3'd1; d_out_sel = 3'd2;
                    rd_b_sel = (ins == `Z80K_EX_SP_IX) ? ix_hi : R_H;
                    if (LST) sp_op = 2'd1;
                end
                if (k == 3'd4) begin
                    addr_sel = 3'd1; d_out_sel = 3'd2;
                    rd_b_sel = (ins == `Z80K_EX_SP_IX) ? (ix_hi + 4'd1) : R_L;
                    if (LST) begin pair_op = 3'd5; pair_sel = (ins == `Z80K_EX_SP_IX) ? ixp : 3'd2; end
                end
            end

            // ------------------------------------------------ block transfer and search
            `Z80K_LDI, `Z80K_LDD, `Z80K_LDIR, `Z80K_LDDR: begin
                if (k == 3'd1) begin                       // MR at HL
                    addr_sel = 3'd5; tmp_we = ST;
                    if (LST) begin pair_op = dn ? 3'd2 : 3'd1; pair_sel = 3'd2; end
                end
                if (k == 3'd2) begin                       // MW(5) at DE
                    addr_sel = 3'd4; d_out_sel = 3'd3;
                    if (T1H) begin pair_op = 3'd2; pair_sel = 3'd0; end            // BC - 1
                    if (T3L) begin pair_op = dn ? 3'd2 : 3'd1; pair_sel = 3'd1; end // DE +- 1
                    if (LST) begin alu_op = 6'd34; f_we = 1'b1; end
                end
                if (k == 3'd3 && LST) pc_op = 3'd2;
            end
            `Z80K_CPI, `Z80K_CPD, `Z80K_CPIR, `Z80K_CPDR: begin
                if (k == 3'd1) begin
                    addr_sel = 3'd5; tmp_we = ST;
                    if (LST) begin pair_op = dn ? 3'd2 : 3'd1; pair_sel = 3'd2; end
                end
                if (k == 3'd2) begin                       // IO(5)
                    alu_op = 6'd35; alu_a_sel = 2'd0; alu_b_sel = 3'd1;
                    if (T1H) begin pair_op = 3'd2; pair_sel = 3'd0; end
                    if (T2H) f_we = 1'b1;
                end
                if (k == 3'd3 && LST) pc_op = 3'd2;
            end
            `Z80K_INI, `Z80K_IND, `Z80K_INIR, `Z80K_INDR: begin
                if (k == 3'd1) begin                       // PR(4) at BC (B before the decrement)
                    addr_sel = 3'd3; tmp_we = ST;
                    if (LST) begin alu_op = 6'd10; alu_b_sel = 3'd2; rd_b_sel = R_B; wd_go = 1'b1; wd_r = R_B; f_we = 1'b1; end
                end
                if (k == 3'd2) begin                       // MW at HL
                    addr_sel = 3'd5; d_out_sel = 3'd3;
                    if (LST) begin pair_op = dn ? 3'd2 : 3'd1; pair_sel = 3'd2; end
                end
                if (k == 3'd3 && LST) pc_op = 3'd2;
            end
            `Z80K_OUTI, `Z80K_OUTD, `Z80K_OUTIR, `Z80K_OUTDR: begin
                if (k == 3'd1) begin                       // MR at HL, B - 1 before the port write
                    addr_sel = 3'd5; tmp_we = ST;
                    if (LST) begin
                        pair_op = dn ? 3'd2 : 3'd1; pair_sel = 3'd2;
                        alu_op = 6'd10; alu_b_sel = 3'd2; rd_b_sel = R_B; wd_go = 1'b1; wd_r = R_B; f_we = 1'b1;
                    end
                end
                if (k == 3'd2) begin addr_sel = 3'd3; d_out_sel = 3'd3; end
                if (k == 3'd3 && LST) pc_op = 3'd2;
            end

            // ------------------------------------------------ 8-bit arithmetic
            `Z80K_ALU_R: if (k == 3'd0) begin
                alu_op = 6'd1 + {3'b0, dst3}; a_we = LST; f_we = LST;
                if (src_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_ALU_HL: if (k == 3'd1) begin
                addr_sel = 3'd5; alu_op = 6'd1 + {3'b0, dst3}; alu_b_sel = 3'd0; a_we = ST; f_we = ST;
            end
            `Z80K_ALU_N: if (k == 3'd1) begin
                alu_op = 6'd1 + {3'b0, dst3}; alu_b_sel = 3'd0; a_we = ST; f_we = ST; pcinc = 1'b1;
            end
            `Z80K_INC_R, `Z80K_DEC_R: if (k == 3'd0) begin
                alu_op = (ins == `Z80K_INC_R) ? 6'd9 : 6'd10; f_we = LST; wd_go = LST; wd_a = dst_a; wd_r = dst4;
                if (dst_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = dst4; end
            end
            `Z80K_INC_HL, `Z80K_DEC_HL: begin
                if (k == 3'd1) begin
                    addr_sel = 3'd5; tmp_we = ST;
                    if (LST) begin
                        alu_op = (ins == `Z80K_INC_HL) ? 6'd9 : 6'd10; alu_b_sel = 3'd1; f_we = 1'b1;
                        tmp_we = 1'b1; tmp_res = 1'b1;
                    end
                end
                if (k == 3'd2) begin addr_sel = 3'd5; d_out_sel = 3'd3; end
            end
            `Z80K_DAA: if (k == 3'd0) begin alu_op = 6'd23; alu_b_sel = 3'd3; a_we = LST; f_we = LST; end
            `Z80K_CPL: if (k == 3'd0) begin alu_op = 6'd24; alu_b_sel = 3'd3; a_we = LST; f_we = LST; end
            `Z80K_SCF: if (k == 3'd0) begin alu_op = 6'd25; alu_b_sel = 3'd3; f_we = LST; end
            `Z80K_CCF: if (k == 3'd0) begin alu_op = 6'd26; alu_b_sel = 3'd3; f_we = LST; end
            `Z80K_NEG: if (k == 3'd0) begin
                alu_op = 6'd3; alu_a_sel = 2'd2; alu_b_sel = 3'd3; a_we = LST; f_we = LST;
            end
            `Z80K_ROT_A: if (k == 3'd0) begin
                alu_op = 6'd19 + {3'b0, ir[5:3]}; alu_b_sel = 3'd3; a_we = LST; f_we = LST;
            end

            // ------------------------------------------------ 16-bit arithmetic
            `Z80K_INC_SS, `Z80K_DEC_SS: if (k == 3'd0 && LST) begin
                if (dd == 2'd3) sp_op = (ins == `Z80K_INC_SS) ? 2'd2 : 2'd1;
                else begin pair_op = (ins == `Z80K_INC_SS) ? 3'd1 : 3'd2; pair_sel = {1'b0, dd}; end
            end
            `Z80K_INC_IX, `Z80K_DEC_IX: if (k == 3'd0 && LST) begin
                pair_op = (ins == `Z80K_INC_IX) ? 3'd1 : 3'd2; pair_sel = ixp;
            end
            `Z80K_ADD_HL_SS, `Z80K_ADD_IX, `Z80K_ADC_HL, `Z80K_SBC_HL: begin
                // the low byte in the first IO cycle, the high byte in the second (blocks 2.3, ops 36-41)
                alu_a_sel = 2'd1; alu_b_sel = 3'd2;
                if (k == 3'd1) begin
                    alu_op = (ins == `Z80K_ADC_HL) ? 6'd37 : (ins == `Z80K_SBC_HL) ? 6'd38 : 6'd36;
                    rd_a_sel = (ins == `Z80K_ADD_IX) ? (ix_hi + 4'd1) : R_L;
                    rd_b_sel = (ins == `Z80K_ADD_IX && dd == 2'd2) ? (ix_hi + 4'd1) : (dd_hi + 4'd1);
                    wd_go = LST; wd_r = rd_a_sel; f_we = LST;
                end
                if (k == 3'd2) begin
                    alu_op = (ins == `Z80K_ADC_HL) ? 6'd40 : (ins == `Z80K_SBC_HL) ? 6'd41 : 6'd39;
                    rd_a_sel = (ins == `Z80K_ADD_IX) ? ix_hi : R_H;
                    rd_b_sel = (ins == `Z80K_ADD_IX && dd == 2'd2) ? ix_hi : dd_hi;
                    wd_go = LST; wd_r = rd_a_sel; f_we = LST;
                end
            end

            // ------------------------------------------------ jumps, calls, returns
            `Z80K_JP, `Z80K_JP_CC: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2) begin
                    wz_op = ST ? 3'd2 : 3'd0;
                    if (LST) pc_op = go ? 3'd4 : 3'd1;
                end
            end
            `Z80K_JP_HL: if (k == 3'd0 && LST) begin pc_op = 3'd6; pair_sel = 3'd2; end
            `Z80K_JP_IX: if (k == 3'd0 && LST) begin pc_op = 3'd6; pair_sel = ixp; end
            `Z80K_JR, `Z80K_JR_CC, `Z80K_DJNZ: begin
                if (k == 3'd0 && ins == `Z80K_DJNZ && LST) begin
                    alu_op = 6'd10; alu_b_sel = 3'd2; rd_b_sel = R_B; wd_go = 1'b1; wd_r = R_B;
                end
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2 && LST) pc_op = 3'd5;
            end
            `Z80K_CALL, `Z80K_CALL_CC: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2) begin
                    wz_op = ST ? 3'd2 : 3'd0;
                    if (LST) begin pc_op = 3'd1; if (go) sp_op = 2'd1; end
                end
                if (k == 3'd3 || k == 3'd4) begin
                    addr_sel = 3'd1; d_out_sel = 3'd2; rd_b_sel = (k == 3'd3) ? R_PCH : R_PCL;
                    if (LST) begin if (k == 3'd3) sp_op = 2'd1; else pc_op = 3'd4; end
                end
            end
            `Z80K_RET, `Z80K_RET_CC, `Z80K_RETI, `Z80K_RETN: begin
                if (k == 3'd1 || k == 3'd2) begin
                    addr_sel = 3'd1;
                    wz_op = ST ? ((k == 3'd1) ? 3'd1 : 3'd2) : 3'd0;
                    if (LST) begin sp_op = 2'd2; if (k == 3'd2) pc_op = 3'd4; end
                end
                if (k == 3'd0 && ins == `Z80K_RETN) c_retn = H3;
            end
            `Z80K_RST: begin
                if (k == 3'd0 && LST) sp_op = 2'd1;
                if (k == 3'd1 || k == 3'd2) begin
                    addr_sel = 3'd1; d_out_sel = 3'd2; rd_b_sel = (k == 3'd1) ? R_PCH : R_PCL;
                    if (LST) begin if (k == 3'd1) sp_op = 2'd1; else pc_op = 3'd7; end
                end
            end

            // ------------------------------------------------ input / output
            `Z80K_IN_A_N, `Z80K_OUT_N_A: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd3 : 3'd0; pcinc = 1'b1; end
                if (k == 3'd2) begin
                    addr_sel = 3'd2;
                    if (ins == `Z80K_OUT_N_A) d_out_sel = 3'd0;
                    else begin alu_b_sel = 3'd0; wd_go = ST; wd_a = 1'b1; end
                end
            end
            `Z80K_IN_R_C: if (k == 3'd1) begin
                addr_sel = 3'd3; alu_op = 6'd32; alu_b_sel = 3'd1; tmp_we = ST; f_we = LST;   // via TMP: IN B,(C) moves BC
                wd_go = LST && (dst3 != 3'd6); wd_a = dst_a; wd_r = dst4;
            end
            `Z80K_OUT_C_R: if (k == 3'd1) begin
                addr_sel = 3'd3;
                if (dst_a) d_out_sel = 3'd0; else begin d_out_sel = 3'd2; rd_b_sel = dst4; end
            end

            // ------------------------------------------------ CPU control
            `Z80K_DI:   if (k == 3'd0) c_di = H3;
            `Z80K_EI:   if (k == 3'd0) c_ei = H3;
            `Z80K_IM:   if (k == 3'd0) c_im = H3;
            `Z80K_HALT: if (k == 3'd0) c_halt = H3;

            // ------------------------------------------------ CB group (on a register or (HL))
            `Z80K_ROT_R: if (k == 3'd0) begin
                alu_op = 6'd11 + {3'b0, ir[5:3]}; f_we = LST; wd_go = LST; wd_a = src_a; wd_r = src4;
                if (src_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_BIT_R: if (k == 3'd0) begin
                alu_op = 6'd27; f_we = LST;
                if (src_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_SET_R, `Z80K_RES_R: if (k == 3'd0) begin
                alu_op = (ins == `Z80K_SET_R) ? 6'd28 : 6'd29; wd_go = LST; wd_a = src_a; wd_r = src4;
                if (src_a) alu_b_sel = 3'd3; else begin alu_b_sel = 3'd2; rd_b_sel = src4; end
            end
            `Z80K_ROT_HL, `Z80K_SET_HL, `Z80K_RES_HL: begin
                if (k == 3'd1) begin
                    addr_sel = 3'd5; tmp_we = ST;
                    if (LST) begin
                        alu_op = (ins == `Z80K_ROT_HL) ? (6'd11 + {3'b0, ir[5:3]}) :
                                 (ins == `Z80K_SET_HL) ? 6'd28 : 6'd29;
                        alu_b_sel = 3'd1; f_we = (ins == `Z80K_ROT_HL);
                        tmp_we = 1'b1; tmp_res = 1'b1;
                    end
                end
                if (k == 3'd2) begin addr_sel = 3'd5; d_out_sel = 3'd3; end
            end
            `Z80K_BIT_HL: if (k == 3'd1) begin
                addr_sel = 3'd5; alu_op = 6'd27; alu_b_sel = 3'd0; f_we = ST;
            end
            `Z80K_RLD, `Z80K_RRD: begin
                if (k == 3'd1) begin addr_sel = 3'd5; tmp_we = ST; end
                if (k == 3'd2) begin
                    alu_op = (ins == `Z80K_RLD) ? 6'd30 : 6'd31; alu_b_sel = 3'd1;
                    if (LST) begin a_we = 1'b1; f_we = 1'b1; tmp_we = 1'b1; tmp_res = 1'b1; end
                end
                if (k == 3'd3) begin addr_sel = 3'd5; d_out_sel = 3'd3; end
            end

            // ------------------------------------------------ (IX+d) / (IY+d)
            `Z80K_LD_R_IXD, `Z80K_LD_IXD_R, `Z80K_ALU_IXD, `Z80K_INC_IXD, `Z80K_DEC_IXD, `Z80K_LD_IXD_N: begin
                if (k == 3'd1) begin wz_op = ST ? 3'd1 : 3'd0; pcinc = 1'b1; end
                if (ins == `Z80K_LD_IXD_N) begin
                    if (k == 3'd2) begin               // OD(5): n, then WZ <- IX + d
                        tmp_we = ST; pcinc = 1'b1;
                        if (LST) begin pair_op = 3'd6; pair_sel = ixp; end
                    end
                    if (k == 3'd3) begin addr_sel = 3'd2; d_out_sel = 3'd3; end
                end else begin
                    if (k == 3'd2 && LST) begin pair_op = 3'd6; pair_sel = ixp; end
                    if (k == 3'd3) begin
                        addr_sel = 3'd2;
                        case (ins)
                            `Z80K_LD_R_IXD: begin alu_b_sel = 3'd0; wd_go = ST; wd_a = dst_a; wd_r = dst4; end
                            `Z80K_ALU_IXD:  begin alu_op = 6'd1 + {3'b0, dst3}; alu_b_sel = 3'd0; a_we = ST; f_we = ST; end
                            `Z80K_LD_IXD_R: begin
                                if (src_a) d_out_sel = 3'd0; else begin d_out_sel = 3'd2; rd_b_sel = src4; end
                            end
                            default: begin             // INC (IX+d), DEC (IX+d): MR(4), then MW
                                tmp_we = ST;
                                if (LST) begin
                                    alu_op = (ins == `Z80K_INC_IXD) ? 6'd9 : 6'd10; alu_b_sel = 3'd1; f_we = 1'b1;
                                    tmp_we = 1'b1; tmp_res = 1'b1;
                                end
                            end
                        endcase
                    end
                    if (k == 3'd4) begin addr_sel = 3'd2; d_out_sel = 3'd3; end   // INC/DEC (IX+d) write
                end
            end
            `Z80K_ROT_IXD, `Z80K_BIT_IXD, `Z80K_RES_IXD, `Z80K_SET_IXD: begin
                if (k == 3'd1) begin
                    addr_sel = 3'd2; tmp_we = ST;
                    if (ins == `Z80K_BIT_IXD) begin alu_op = 6'd27; alu_b_sel = 3'd0; f_we = ST; tmp_we = 1'b0; end
                    else if (LST) begin
                        alu_op = (ins == `Z80K_ROT_IXD) ? (6'd11 + {3'b0, ir[5:3]}) :
                                 (ins == `Z80K_SET_IXD) ? 6'd28 : 6'd29;
                        alu_b_sel = 3'd1; f_we = (ins == `Z80K_ROT_IXD);
                        tmp_we = 1'b1; tmp_res = 1'b1;
                    end
                end
                if (k == 3'd2) begin addr_sel = 3'd2; d_out_sel = 3'd3; end
            end
            default: ;
            endcase
        end

        // operand byte reads: the address is PC, which moves at the last half
        if (pcinc) begin addr_sel = 3'd0; if (LST) pc_op = 3'd1; end
        // register write from the ALU result
        if (wd_go) begin
            if (wd_a) a_we = 1'b1; else begin wr_we = 1'b1; wr_sel = wd_r; end
        end
    end

    // ---------------------------------------------------------------- IFF, IM, EI, HALT, NMI
    // a bus request sampled at the same edge blocks both interrupts (spec 8.4 item 4)
    wire go_n = nmi_pend && busrq_n;
    wire go_i = !nmi_pend && !int_n && iff1 && !ei_cur && busrq_n;
    wire sample = samp_last && !resp && last_any;

    always @(posedge clk) begin
        nmi_q <= nmi_n;
        if (reset) begin
            ir <= 8'h00; prefix <= 3'd0; m <= 3'd0; irk <= 3'd0;
            iff1 <= 1'b0; iff2_r <= 1'b0; im <= 2'd0; tmp_r <= 8'h00;
            nmi_pend <= 1'b0; ei_cur <= 1'b0; halt_st <= 1'b0; gon <= 1'b0; goi <= 1'b0;
            mc_type <= OCF; mc_len <= 3'd4; halt_n <= 1'b1;
        end else begin
            // NMI edge detector: every model edge (spec 8.4 item 6)
            if (nmi_q && !nmi_n) nmi_pend <= 1'b1;

            // sampling point
            if (samp_last) begin
                gon <= sample && go_n;
                goi <= sample && go_i;
                if (sample && (go_n || go_i)) begin
                    halt_st <= 1'b0;
                    if (go_n && !(nmi_q && !nmi_n)) nmi_pend <= 1'b0;
                end
            end

            // data captured at the half that ends where d_in is taken
            if (ir_load) ir <= d_in;
            if (tmp_we) tmp_r <= tmp_res ? result : d_in;

            // IFF, IM, EI delay, HALT
            if (c_di)   begin iff1 <= 1'b0; iff2_r <= 1'b0; end
            if (c_ei)   begin iff1 <= 1'b1; iff2_r <= 1'b1; ei_cur <= 1'b1; end
            if (c_retn) iff1 <= iff2_r;
            if (c_im)   im <= (ir[4:3] == 2'd0) ? 2'd0 : (ir[4:3] == 2'd2) ? 2'd1 : 2'd2;
            if (c_halt) halt_st <= 1'b1;
            // response starts: IFF changes at T1H of its first cycle (LD A,I read IFF2 before this)
            if (resp && m == 3'd0 && T1H) begin
                iff1 <= 1'b0;
                if (irk != 3'd1) iff2_r <= 1'b0;
            end
            // halt_n: falls at the edge that starts T4L of the HALT M1, rises at T4L of the accepting halted M1
            if (mc_type == OCF && ok && !ph && t == 3'd4) halt_n <= ~halt_st;

            // The length of an opcode fetch is known only once the opcode is in IR (OCF(5) of PUSH, OCF(6) of INC ss, ...):
            // set it at H3, the first half with decode valid, before samp_last / mc_end of the cycle can use it.
            if (H3 && kind_en && !is_prefix && mc_type == OCF) mc_len <= plan_len[3*m +: 3];

            // end of an M cycle: step the plan
            if (LST) begin
                if (resp) begin
                    if (last_resp) begin
                        irk <= 3'd0; m <= 3'd0; mc_type <= OCF; mc_len <= 3'd4;
                    end else begin
                        m <= m + 3'd1;
                        mc_type <= (m < 3'd2) ? MWR : MRD;
                        mc_len <= 3'd3;
                    end
                end else if (is_prefix && !halted_m1) begin
                    // a prefix byte: fetch on
                    prefix <= (prefix == 3'd0) ? ((ir == 8'hCB) ? 3'd1 : (ir == 8'hDD) ? 3'd2 :
                                                  (ir == 8'hED) ? 3'd3 : 3'd4)
                                               : ((prefix == 3'd2) ? 3'd5 : 3'd6);
                    m <= m + 3'd1;
                    if (prefix != 3'd0) begin mc_type <= MRD; mc_len <= 3'd3; end    // DD CB: the d byte
                    else begin mc_type <= OCF; mc_len <= 3'd4; end
                end else if (ddcb_pre) begin
                    m <= m + 3'd1;
                    mc_type <= MRD;
                    mc_len <= (m == 3'd2) ? 3'd5 : plan_len[3*4 +: 3];
                    if (m == 3'd3) mc_type <= plan_type[3*4 +: 3];
                end else if (last_any) begin
                    prefix <= 3'd0; m <= 3'd0; ei_cur <= 1'b0;
                    if (gon) begin
                        irk <= 3'd1; mc_type <= OCF; mc_len <= 3'd5;
                    end else if (goi) begin
                        irk <= (im == 2'd0) ? 3'd2 : (im == 2'd1) ? 3'd3 : 3'd4;
                        mc_type <= INTA; mc_len <= (im == 2'd0) ? 3'd6 : 3'd7;
                    end else begin
                        mc_type <= OCF; mc_len <= 3'd4;
                    end
                end else begin
                    m <= m + 3'd1;
                    mc_type <= plan_type[3*(m + 3'd1) +: 3];
                    mc_len  <= (s3 && !go && (m == 3'd1)) ? 3'd3 : plan_len[3*(m + 3'd1) +: 3];
                end
            end
        end
    end

    wire unused_ok = &{1'b0, specified, R_C, R_H, PRD, PWR, IOC, tw};
endmodule
