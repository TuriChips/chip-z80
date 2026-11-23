// z80_timing: T-state counter, half phase, WAIT/Tw, BUSRQ/Tx, bus strobes.
// Ports: docs/blocks.md §3 (z80_timing) at 3cb014a. Spec §4.0-4.5, §5, §6.1, §8.4 at 3cb014a.
//
// One model clock = one half T state. State (t, ph, tw, tx) names the half
// that is running. Every pin is a flop loaded at the edge that starts a half,
// from the NEXT-half state, so a pin is stable for the whole half.
//
// Open spec PRs, text followed as at 3cb014a: #17 (BUSRQ release / Tx halves,
// reset halves E+1/E+2, IN/OUT d_oe) and #24 (d_oe = 0 in T4,T5 of lengthened
// writes). Each spot is marked with its PR number below.
//
// Exception (documented): m1_n in T1H. mc_type of the new cycle is presented
// by control at the same edge that starts T1H, so a flop cannot see it yet.
// m1_n is therefore m1_q (1 in T1H) ANDed with a term from the registered
// mc_type while the T1H half runs. Every other pin is 1/0 inactive in T1H.
module z80_timing (
    input  wire       clk,
    input  wire       reset,
    input  wire       wait_n,
    input  wire       busrq_n,
    input  wire [2:0] mc_type,
    input  wire [2:0] mc_len,
    output reg  [2:0] t,
    output reg        tw,
    output reg        ph,
    output reg        tx,
    output wire       d_strobe,
    output wire       samp_last,
    output wire       mc_end,
    output wire       rfsh,
    output wire       r_inc,
    output wire       m1_n,
    output reg        mreq_n,
    output reg        iorq_n,
    output reg        rd_n,
    output reg        wr_n,
    output reg        rfsh_n,
    output reg        d_oe,
    output reg        bus_oe,
    output reg        busak_n
);
    localparam OCF = 3'd0, MRD = 3'd1, MWR = 3'd2, PRD = 3'd3,
               PWR = 3'd4, INTA = 3'd6;

    reg  m1_q;
    reg  run;        // 0 while in reset (incl. the half after release, E+1)
    reg  wait_s;     // WAIT sampled at the edge that started this L half
    reg  bq_s;       // BUSRQ sampled 0 at the edge that started the last T
    reg  tx_last;    // this Tx is Txn: busrq_n was sampled 1 at its start

    // ---- what the current M cycle is (mc_type/mc_len are stable all cycle)
    wire is_ocf  = (mc_type == OCF);
    wire is_inta = (mc_type == INTA);
    // t of the half that samples WAIT (2 for OCF/MRD/MWR, 3 for PRD/PWR, 4 for INTA)
    wire [2:0] wt = (mc_type == OCF || mc_type == MRD || mc_type == MWR) ? 3'd2 :
                    (mc_type == PRD || mc_type == PWR) ? 3'd3 :
                    (mc_type == INTA) ? 3'd4 : 3'd0;
    wire at_wt   = (wt != 3'd0) && (t == wt);   // T_wt or a Tw after it
    // an L half that ends in a WAIT-inserted Tw
    wire tw_next = ph && !tx && at_wt && !wait_s;
    wire last_t  = (t == mc_len);               // never a Tw (wt < every len)

    assign mc_end    = run && !tx && ph && last_t;
    assign samp_last = run && !tx && ph && ((t + 3'd1) == mc_len) && !tw_next;
    assign d_strobe  = run && !tx && (
        ((is_ocf || is_inta) && ph && at_wt && wait_s) ||
        (mc_type == MRD && !ph && t == 3'd3 && !tw) ||
        (mc_type == PRD && !ph && t == 3'd4 && !tw));
    assign rfsh      = run && !tx && (is_ocf && (t == 3'd3 || t == 3'd4) ||
                                      is_inta && (t == 3'd5 || t == 3'd6));
    assign r_inc     = run && !tx && ph && (is_ocf && t == 3'd4 || is_inta && t == 3'd6);

    // ---- next-half state
    reg [2:0] n_t;
    reg       n_ph, n_tw, n_tx, n_txl, n_run;
    always @* begin
        n_t = t; n_ph = ph; n_tw = tw; n_tx = tx; n_txl = tx_last; n_run = 1'b1;
        if (reset) begin
            // In reset: run = 0, ph held 0 (an H-half marker).
            n_run = 1'b0; n_t = 3'd1; n_ph = 1'b0; n_tw = 1'b0; n_tx = 1'b0; n_txl = 1'b0;
        end else if (!run) begin
            // PR #17: reset_n released at rising edge E is seen here at E+1 (a falling
            // edge): half E+1 is still a reset half; T1H starts at E+2
            // (spec §5 item 3a, chip-z80#11).
            n_t = 3'd1; n_tw = 1'b0; n_tx = 1'b0; n_txl = 1'b0;
            if (!ph) begin n_ph = 1'b1; n_run = 1'b0; end
            else     begin n_ph = 1'b0; n_run = 1'b1; end
        end else if (!ph) begin
            n_ph = 1'b1;                       // H -> L, same T
        end else begin
            n_ph = 1'b0;                       // L -> H
            if (tx) begin
                // PR #17: Tx halves; busrq_n re-sampled at each edge that starts a Tx
                // bus request: busrq_n sampled at the edge that starts each Tx
                if (tx_last) begin n_tx = 1'b0; n_txl = 1'b0; n_t = 3'd1; end
                else n_txl = busrq_n;
            end else if (tw_next) begin
                n_tw = 1'b1;
            end else if (last_t) begin
                n_tw = 1'b0; n_t = 3'd1;
                if (bq_s) begin n_tx = 1'b1; n_txl = 1'b0; end
            end else begin
                n_tw = 1'b0; n_t = t + 3'd1;
            end
        end
    end

    // pins for the next half, from the next-half state. In T1H (n_t==1, !n_ph,
    // !n_tx) mc_type is not yet the new cycle's, so everything is inactive.
    wire t1h  = (n_t == 3'd1) && !n_ph;
    wire h = !n_ph, l = n_ph;
    reg p_m1, p_mreq, p_iorq, p_rd, p_wr, p_rfsh, p_doe;
    always @* begin
        p_m1 = 1'b1; p_mreq = 1'b1; p_iorq = 1'b1; p_rd = 1'b1; p_wr = 1'b1;
        p_rfsh = 1'b1; p_doe = 1'b0;
        if (n_run && !n_tx && !t1h) begin
            case (mc_type)
            OCF: begin
                p_m1   = !(n_t <= 3'd2);
                p_mreq = !((n_t == 3'd1 && l) || n_t == 3'd2 || (n_t == 3'd3 && l) || (n_t == 3'd4 && h));
                p_rd   = !((n_t == 3'd1 && l) || n_t == 3'd2);
                p_rfsh = !(n_t == 3'd3 || n_t == 3'd4);
            end
            MRD: begin
                p_mreq = !((n_t == 3'd1 && l) || n_t == 3'd2 || (n_t == 3'd3 && h));
                p_rd   = p_mreq;
            end
            MWR: begin
                p_mreq = !((n_t == 3'd1 && l) || n_t == 3'd2 || (n_t == 3'd3 && h));
                p_wr   = !((n_t == 3'd2 && (l || n_tw)) || (n_t == 3'd3 && h));
                // d_oe falls at the rising edge after T3L: 0 in T4, T5 (spec §4.2, PR #24)
                p_doe  = (n_t == 3'd1 && l) || n_t == 3'd2 || n_t == 3'd3;
            end
            PRD: begin
                p_iorq = !(n_t == 3'd2 || n_t == 3'd3 || (n_t == 3'd4 && h));
                p_rd   = p_iorq;
            end
            PWR: begin
                p_iorq = !(n_t == 3'd2 || n_t == 3'd3 || (n_t == 3'd4 && h));
                p_wr   = p_iorq;
                p_doe  = (n_t == 3'd1 && l) || (n_t >= 3'd2 && n_t <= 3'd4);
            end
            INTA: begin
                p_m1   = !(n_t <= 3'd4);
                p_iorq = !((n_t == 3'd3 && l) || n_t == 3'd4);
                p_mreq = !((n_t == 3'd5 && l) || (n_t == 3'd6 && h));
                p_rfsh = !(n_t == 3'd5 || n_t == 3'd6);
            end
            default: ;   // IO, unused: all inactive
            endcase
        end
    end

    always @(posedge clk) begin
        run <= n_run; t <= n_t; ph <= n_ph; tw <= n_tw; tx <= n_tx; tx_last <= n_txl;
        // WAIT: sampled at the edge that starts the L half of T_wt / each TwL
        if (run && !ph && !tx && at_wt) wait_s <= wait_n;
        // BUSRQ: sampled at the edge that ends the L half before the last T
        if (!tx && ph && ((t + 3'd1) == mc_len) && !tw_next && run) bq_s <= !busrq_n;
        if (reset) bq_s <= 1'b0;
        m1_q    <= p_m1;
        mreq_n  <= p_mreq; iorq_n <= p_iorq; rd_n <= p_rd; wr_n <= p_wr;
        rfsh_n  <= p_rfsh; d_oe <= p_doe;
        // bus_oe: 0 in reset and in every Tx half; busak_n: 0 in Tx except TxnL
        bus_oe  <= n_run && !n_tx;
        busak_n <= !(n_run && n_tx) || (n_txl && n_ph);
    end

    // m1_n in T1H comes from the registered mc_type (see header)
    wire t1h_now = run && !tx && !ph && (t == 3'd1);
    assign m1_n  = m1_q & ~(t1h_now & (mc_type == OCF || mc_type == INTA));
endmodule
