// z80_alu: A, F, A', F', EX AF,AF' bank bit, c16/z16 latches, 8-bit ALU.
// Ports and alu_op codes: docs/blocks.md section 3 (z80_alu) and 2.3, 2.5 (at 3cb014a).
// Flags: spec 6.2; F[5] = F[3] = 0 on every flag update (spec 6.3 rule 1).
// Rows tied to an open decision carry a "decision N" comment.
module z80_alu (
    input  wire       clk,
    input  wire       reset,     // active high, synchronous
    input  wire [5:0] op,
    input  wire [7:0] a_in,
    input  wire [7:0] b,
    input  wire       a_we,
    input  wire       f_we,
    input  wire       f_load,
    input  wire       af_swap,
    input  wire [2:0] bit_n,
    input  wire       iff2,
    input  wire       bc_nz,
    output wire [7:0] a_out,
    output wire [7:0] f_out,
    output reg  [7:0] result
);
    // F = S Z 5 H 3 P/V N C
    localparam FS = 7, FZ = 6, FH = 4, FP = 2, FN = 1, FC = 0;

    reg [7:0] a_r [0:1];
    reg [7:0] f_r [0:1];
    reg       bank;
    reg       c16, z16;

    assign a_out = a_r[bank];
    assign f_out = f_r[bank];

    wire [7:0] a = a_out;
    wire [7:0] f = f_out;
    wire       cf = f[FC];

    // ---- adder / subtractor (shared by ops 1-4, 8, 35-41) ----------------------------------
    reg        is_sub, cin;
    always @* begin
        is_sub = 1'b0;
        cin    = 1'b0;
        case (op)
            6'd1:  begin is_sub = 1'b0; cin = 1'b0; end   // ADD
            6'd2:  begin is_sub = 1'b0; cin = cf;   end   // ADC
            6'd3, 6'd8, 6'd35: begin is_sub = 1'b1; cin = 1'b0; end // SUB, CP, BLKCP
            6'd4:  begin is_sub = 1'b1; cin = cf;   end   // SBC
            6'd36: begin is_sub = 1'b0; cin = 1'b0; end   // ADD16L
            6'd37: begin is_sub = 1'b0; cin = cf;   end   // ADC16L
            6'd38: begin is_sub = 1'b1; cin = cf;   end   // SBC16L
            6'd39, 6'd40: begin is_sub = 1'b0; cin = c16; end // ADD16H, ADC16H
            6'd41: begin is_sub = 1'b1; cin = c16;  end   // SBC16H
            default: begin is_sub = 1'b0; cin = 1'b0; end
        endcase
    end

    wire [8:0] sum9  = {1'b0, a_in} + {1'b0, b} + {8'b0, cin};
    wire [8:0] dif9  = {1'b0, a_in} - {1'b0, b} - {8'b0, cin};
    wire [8:0] as9   = is_sub ? dif9 : sum9;
    wire [7:0] as8   = as9[7:0];
    wire       as_c  = as9[8];                       // carry out, or borrow for subtract
    // carry (add) or borrow (sub) into bit 4: a[4] ^ b[4] ^ r[4] holds for both
    wire       as_h  = a_in[4] ^ b[4] ^ as8[4];
    wire       as_v  = is_sub ? ((a_in[7] ^ b[7]) & (a_in[7] ^ as8[7]))
                              : ((a_in[7] ^ as8[7]) & (b[7] ^ as8[7]));

    // ---- INC / DEC -----------------------------------------------------------------------
    wire [7:0] inc8 = b + 8'd1;
    wire [7:0] dec8 = b - 8'd1;

    // ---- rotates and shifts (11-18 on b; 19-22 accumulator forms) --------------------------
    reg  [7:0] rs;
    reg        rs_c;
    always @* begin
        rs = b; rs_c = 1'b0;
        case (op)
            6'd11, 6'd19: begin rs = {b[6:0], b[7]}; rs_c = b[7]; end  // RLC, RLCA
            6'd12, 6'd20: begin rs = {b[0], b[7:1]}; rs_c = b[0]; end  // RRC, RRCA
            6'd13, 6'd21: begin rs = {b[6:0], cf};   rs_c = b[7]; end  // RL, RLA
            6'd14, 6'd22: begin rs = {cf, b[7:1]};   rs_c = b[0]; end  // RR, RRA
            6'd15:        begin rs = {b[6:0], 1'b0}; rs_c = b[7]; end  // SLA
            6'd16:        begin rs = {b[7], b[7:1]}; rs_c = b[0]; end  // SRA
            // op 17 (SLL) is unused until Sai rules on decision 9 (#14 / PR #23): falls to default
            6'd18:        begin rs = {1'b0, b[7:1]}; rs_c = b[0]; end  // SRL
            default: ;
        endcase
    end

    // ---- DAA (decision 8: proposed NMOS rule, Sean Young; inside the 13-row table it agrees) ----
    wire       daa_hi  = cf | (b > 8'h99);           // decision 8
    wire       daa_lo  = f[FH] | (b[3:0] > 4'd9);    // decision 8
    wire [7:0] daa_add = {daa_hi ? 4'h6 : 4'h0, daa_lo ? 4'h6 : 4'h0};
    wire [7:0] daa_res = f[FN] ? (b - daa_add) : (b + daa_add);
    wire       daa_c   = daa_hi;                     // decision 8
    wire       daa_h   = f[FN] ? (f[FH] & (b[3:0] < 4'd6)) : (b[3:0] > 4'd9); // decision 8

    // ---- RLD / RRD ---------------------------------------------------------------------------
    wire [7:0] rld_a = {a[7:4], b[7:4]};
    wire [7:0] rrd_a = {a[7:4], b[3:0]};

    // ---- BIT / SET / RES -----------------------------------------------------------------
    wire [7:0] bitmask = 8'd1 << bit_n;

    // ---- result, new A, new F --------------------------------------------------------------
    reg  [7:0] nf;        // flag byte if updated
    reg        fupd;      // this op updates F when f_we = 1
    reg        a_ok;      // the op may write A
    reg        lat_upd;   // ops 36-38: update c16/z16 with f_we

    function [7:0] szp(input [7:0] r);   // S, Z, P of r; everything else 0
        szp = {r[7], (r == 8'd0), 1'b0, 1'b0, 1'b0, ~^r, 1'b0, 1'b0};
    endfunction

    always @* begin
        result = b;
        nf     = f;
        fupd   = 1'b0;
        lat_upd = 1'b0;
        a_ok   = 1'b1;
        case (op)
            6'd0: result = b;                                  // PASS
            6'd1, 6'd2, 6'd3, 6'd4, 6'd8: begin                // ADD ADC SUB SBC CP
                result = as8;
                fupd = 1'b1;
                nf = {as8[7], (as8 == 8'd0), 1'b0, as_h, 1'b0, as_v, is_sub, as_c};
                if (op == 6'd8) a_ok = 1'b0;                   // CP never writes A
            end
            6'd5: begin result = a_in & b; fupd = 1'b1; nf = szp(result); nf[FH] = 1'b1; end  // AND
            6'd6: begin result = a_in ^ b; fupd = 1'b1; nf = szp(result); end                 // XOR
            6'd7: begin result = a_in | b; fupd = 1'b1; nf = szp(result); end                 // OR
            6'd9: begin                                        // INC
                result = inc8; fupd = 1'b1;
                nf = {inc8[7], (inc8 == 8'd0), 1'b0, (b[3:0] == 4'hF), 1'b0, (b == 8'h7F), 1'b0, cf};
            end
            6'd10: begin                                       // DEC
                result = dec8; fupd = 1'b1;
                nf = {dec8[7], (dec8 == 8'd0), 1'b0, (b[3:0] == 4'h0), 1'b0, (b == 8'h80), 1'b1, cf};
            end
            6'd11, 6'd12, 6'd13, 6'd14, 6'd15, 6'd16, 6'd18: begin  // CB rotates/shifts
                result = rs; fupd = 1'b1;
                nf = szp(rs); nf[FC] = rs_c;
            end
            6'd19, 6'd20, 6'd21, 6'd22: begin                  // RLCA RRCA RLA RRA
                result = rs; fupd = 1'b1;
                nf = {f[FS], f[FZ], 1'b0, 1'b0, 1'b0, f[FP], 1'b0, rs_c};
            end
            6'd23: begin                                       // DAA (decision 8)
                result = daa_res; fupd = 1'b1;
                nf = szp(daa_res); nf[FH] = daa_h; nf[FN] = f[FN]; nf[FC] = daa_c;
            end
            6'd24: begin                                       // CPL
                result = ~b; fupd = 1'b1;
                nf = {f[FS], f[FZ], 1'b0, 1'b1, 1'b0, f[FP], 1'b1, cf};
            end
            6'd25: begin                                       // SCF
                result = b; fupd = 1'b1;
                nf = {f[FS], f[FZ], 1'b0, 1'b0, 1'b0, f[FP], 1'b0, 1'b1};
            end
            6'd26: begin                                       // CCF
                result = b; fupd = 1'b1;
                nf = {f[FS], f[FZ], 1'b0, cf /* decision 6 (Mostek): H = old C */, 1'b0, f[FP], 1'b0, ~cf};
            end
            6'd27: begin                                       // BIT (S, P/V are X: kept)
                result = b; fupd = 1'b1;
                nf = {f[FS], ~|(b & bitmask), 1'b0, 1'b1, 1'b0, f[FP], 1'b0, cf};
            end
            6'd28: result = b | bitmask;                       // SET, no flags
            6'd29: result = b & ~bitmask;                      // RES, no flags
            6'd30: begin                                       // RLD
                result = {b[3:0], a[3:0]};
            end
            6'd31: begin                                       // RRD
                result = {a[3:0], b[7:4]};
            end
            6'd32: begin                                       // IN
                result = b; fupd = 1'b1;
                nf = szp(b); nf[FC] = cf;
            end
            6'd33: begin                                       // LDAIR
                result = b; fupd = 1'b1;
                nf = {b[7], (b == 8'd0), 1'b0, 1'b0, 1'b0, iff2, 1'b0, cf};
            end
            6'd34: begin                                       // BLKLD
                result = b; fupd = 1'b1;
                // decision 6 (Mostek): S, Z kept
                nf = {f[FS], f[FZ], 1'b0, 1'b0, 1'b0, bc_nz, 1'b0, cf};
            end
            6'd35: begin                                       // BLKCP
                result = as8; fupd = 1'b1; a_ok = 1'b0;
                // decision 6 (Mostek): H = borrow from bit 4 of a_in - b
                nf = {as8[7], (as8 == 8'd0), 1'b0, as_h, 1'b0, bc_nz, 1'b1, cf};
            end
            6'd36, 6'd37, 6'd38: begin                         // ADD16L ADC16L SBC16L
                result = as8; lat_upd = 1'b1;                  // F unchanged
            end
            6'd39: begin                                       // ADD16H
                result = as8; fupd = 1'b1;
                nf = {f[FS], f[FZ], 1'b0, as_h, 1'b0, f[FP], 1'b0, as_c};
            end
            6'd40, 6'd41: begin                                // ADC16H SBC16H
                result = as8; fupd = 1'b1;
                nf = {as8[7], (as8 == 8'd0) & z16, 1'b0, as_h, 1'b0, as_v, is_sub, as_c};
            end
            default: result = b;                               // 17 (SLL, decision 9), 42-63: none
        endcase
    end

    // RLD/RRD: the new A and its flags (S, Z, P of the new A; H = N = 0; C kept). `result` is the
    // byte written back to memory, so A comes from rd_new, not from `result`.
    wire [7:0] rd_new = (op == 6'd30) ? rld_a : rrd_a;
    wire       is_rd  = (op == 6'd30) | (op == 6'd31);
    wire [7:0] f_rd   = szp(rd_new) | {7'b0, cf};

    wire       a_wr   = a_we & a_ok;
    wire [7:0] a_nxt  = is_rd ? rd_new : result;
    wire       f_up   = f_we & (fupd | is_rd);
    wire [7:0] f_nxt  = is_rd ? f_rd : nf & 8'hD7;            // F[5] = F[3] = 0 on every update

    integer i;
    always @(posedge clk) begin
        if (reset) begin
            for (i = 0; i < 2; i = i + 1) begin
                a_r[i] <= 8'd0;
                f_r[i] <= 8'd0;
            end
            bank <= 1'b0;
            c16  <= 1'b0;
            z16  <= 1'b0;
        end else begin
            if (af_swap) bank <= ~bank;
            if (a_wr) a_r[bank] <= a_nxt;
            if (f_load)    f_r[bank] <= b;                    // wins over f_we
            else if (f_up) f_r[bank] <= f_nxt;
            if (f_we & lat_upd) begin
                c16 <= as_c;
                z16 <= (as8 == 8'd0);
            end
        end
    end
endmodule
