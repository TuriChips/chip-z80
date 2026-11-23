// z80_regs: register file, address latch WZ, 16-bit address arithmetic, address mux.
// Contract: docs/blocks.md sections 2.2 and 3. Owner: Ada.
// Every *_we / *_op acts at the rising clk edge that ends the half it is asserted in.
module z80_regs (
    input  wire        clk,
    input  wire        reset,
    input  wire [7:0]  d_in,
    input  wire [7:0]  wdata,
    input  wire [3:0]  wr_sel,
    input  wire        wr_we,
    input  wire [3:0]  rd_a_sel,
    input  wire [3:0]  rd_b_sel,
    input  wire [2:0]  pair_sel,
    input  wire [2:0]  pair_op,
    input  wire [2:0]  pc_op,
    input  wire [1:0]  sp_op,
    input  wire [2:0]  wz_op,
    input  wire [7:0]  rst_vec,
    input  wire [7:0]  a_val,
    input  wire [2:0]  addr_sel,
    input  wire        rfsh,
    input  wire        r_inc,
    output wire [7:0]  rd_a,
    output wire [7:0]  rd_b,
    output wire [15:0] addr,
    output wire        bc_nz,
    output wire        b_nz,
    output wire [15:0] pc
);
    // State. Index 0/1 of bc, de, hl is the register bank; exx selects the current one.
    reg [15:0] bc [0:1];
    reg [15:0] de [0:1];
    reg [15:0] hl [0:1];
    reg [15:0] ix, iy, sp, pcr, wz;
    reg [7:0]  ir_i, ir_r;   // I and R
    reg        exx;

    // Next state
    reg [15:0] n_bc [0:1];
    reg [15:0] n_de [0:1];
    reg [15:0] n_hl [0:1];
    reg [15:0] n_ix, n_iy, n_sp, n_pc, n_wz;
    reg [7:0]  n_i, n_r;
    reg        n_exx;

    // Current-bank views
    wire [15:0] cbc = bc[exx];
    wire [15:0] cde = de[exx];
    wire [15:0] chl = hl[exx];

    // Selected pair (pair_sel)
    reg [15:0] pv;
    always @* begin
        case (pair_sel)
            3'd0:    pv = cbc;
            3'd1:    pv = cde;
            3'd2:    pv = chl;
            3'd3:    pv = ix;
            3'd4:    pv = iy;
            default: pv = 16'h0000;
        endcase
    end

    wire [15:0] wz_sext = {{8{wz[7]}}, wz[7:0]};

    // Byte read by r8 code
    function [7:0] rd8(input [3:0] sel);
        case (sel)
            4'd0:  rd8 = cbc[15:8];
            4'd1:  rd8 = cbc[7:0];
            4'd2:  rd8 = cde[15:8];
            4'd3:  rd8 = cde[7:0];
            4'd4:  rd8 = chl[15:8];
            4'd5:  rd8 = chl[7:0];
            4'd6:  rd8 = ir_i;
            4'd7:  rd8 = ir_r;
            4'd8:  rd8 = ix[15:8];
            4'd9:  rd8 = ix[7:0];
            4'd10: rd8 = iy[15:8];
            4'd11: rd8 = iy[7:0];
            4'd12: rd8 = sp[15:8];
            4'd13: rd8 = sp[7:0];
            4'd14: rd8 = pcr[15:8];
            default: rd8 = pcr[7:0];
        endcase
    endfunction
    assign rd_a = rd8(rd_a_sel);
    assign rd_b = rd8(rd_b_sel);

    assign bc_nz = (cbc != 16'h0000);
    assign b_nz  = (cbc[15:8] != 8'h00);
    assign pc    = pcr;

    reg [15:0] a_mux;
    always @* begin
        case (addr_sel)
            3'd0:    a_mux = pcr;
            3'd1:    a_mux = sp;
            3'd2:    a_mux = wz;
            3'd3:    a_mux = cbc;
            3'd4:    a_mux = cde;
            3'd5:    a_mux = chl;
            default: a_mux = 16'h0000;
        endcase
    end
    assign addr = rfsh ? {ir_i, ir_r} : a_mux;

    // Pair write value and enable (pair_op 1, 2, 5)
    reg [15:0] pw;
    reg        pw_en;
    always @* begin
        pw_en = 1'b0;
        pw    = pv;
        case (pair_op)
            3'd1: begin pw_en = 1'b1; pw = pv + 16'd1; end
            3'd2: begin pw_en = 1'b1; pw = pv - 16'd1; end
            3'd5: begin pw_en = 1'b1; pw = wz;         end
            default: ;
        endcase
    end

    always @* begin
        n_bc[0] = bc[0]; n_bc[1] = bc[1];
        n_de[0] = de[0]; n_de[1] = de[1];
        n_hl[0] = hl[0]; n_hl[1] = hl[1];
        n_ix = ix; n_iy = iy; n_sp = sp; n_pc = pcr; n_wz = wz;
        n_i = ir_i; n_r = ir_r; n_exx = exx;

        // pair_op
        if (pw_en) begin
            case (pair_sel)
                3'd0: n_bc[exx] = pw;
                3'd1: n_de[exx] = pw;
                3'd2: n_hl[exx] = pw;
                3'd3: n_ix = pw;
                3'd4: n_iy = pw;
                default: ;
            endcase
        end
        if (pair_op == 3'd3) begin       // EX DE,HL (current bank)
            n_de[exx] = chl;
            n_hl[exx] = cde;
        end
        if (pair_op == 3'd4) n_exx = ~exx; // EXX: swap the three pairs with their alternates
        if (pair_op == 3'd6) n_wz = pv + wz_sext;

        // pc_op
        case (pc_op)
            3'd1: n_pc = pcr + 16'd1;
            3'd2: n_pc = pcr - 16'd2;
            3'd3: n_pc = {d_in, wz[7:0]};
            3'd4: n_pc = wz;
            3'd5: n_pc = pcr + wz_sext;
            3'd6: n_pc = pv;
            3'd7: n_pc = {8'h00, rst_vec};
            default: ;
        endcase

        // sp_op
        case (sp_op)
            2'd1: n_sp = sp - 16'd1;
            2'd2: n_sp = sp + 16'd1;
            2'd3: n_sp = pv;
            default: ;
        endcase

        // wz_op (pair_op 6 above uses WZ; control never combines it with wz_op)
        case (wz_op)
            3'd1: n_wz[7:0]  = d_in;
            3'd2: n_wz[15:8] = d_in;
            3'd3: n_wz = {a_val, d_in};
            3'd4: n_wz = {ir_i, d_in};
            3'd5: n_wz = wz + 16'd1;
            default: ;
        endcase

        // R refresh increment (R[6:0] only); a wr_we to R below wins
        if (r_inc) n_r[6:0] = ir_r[6:0] + 7'd1;

        // r8 write (wins over the above if it hits the same register)
        if (wr_we) begin
            case (wr_sel)
                4'd0:  n_bc[exx][15:8] = wdata;
                4'd1:  n_bc[exx][7:0]  = wdata;
                4'd2:  n_de[exx][15:8] = wdata;
                4'd3:  n_de[exx][7:0]  = wdata;
                4'd4:  n_hl[exx][15:8] = wdata;
                4'd5:  n_hl[exx][7:0]  = wdata;
                4'd6:  n_i = wdata;
                4'd7:  n_r = wdata;
                4'd8:  n_ix[15:8] = wdata;
                4'd9:  n_ix[7:0]  = wdata;
                4'd10: n_iy[15:8] = wdata;
                4'd11: n_iy[7:0]  = wdata;
                4'd12: n_sp[15:8] = wdata;
                4'd13: n_sp[7:0]  = wdata;
                4'd14: n_pc[15:8] = wdata;
                4'd15: n_pc[7:0]  = wdata;
            endcase
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            bc[0] <= 16'h0; bc[1] <= 16'h0;
            de[0] <= 16'h0; de[1] <= 16'h0;
            hl[0] <= 16'h0; hl[1] <= 16'h0;
            ix <= 16'h0; iy <= 16'h0; sp <= 16'h0; pcr <= 16'h0; wz <= 16'h0;
            ir_i <= 8'h00; ir_r <= 8'h00; exx <= 1'b0;
        end else begin
            bc[0] <= n_bc[0]; bc[1] <= n_bc[1];
            de[0] <= n_de[0]; de[1] <= n_de[1];
            hl[0] <= n_hl[0]; hl[1] <= n_hl[1];
            ix <= n_ix; iy <= n_iy; sp <= n_sp; pcr <= n_pc; wz <= n_wz;
            ir_i <= n_i; ir_r <= n_r; exx <= n_exx;
        end
    end
endmodule
