// z80_system: one z80, 64 KiB memory + 256-byte I/O space (z80_mem x2), data-bus source mux,
// stimulus pass-through, bus_conflict, and the CP/M stub of spec section 9. Ports: docs/blocks.md section 3.
// Simulation only: never synthesized (TOP stays z80). Owner: Zura.
//
// CP/M stub (CPM = 1), what the CPU sees on memory reads at 0000H-0007H (overlay; RAM is untouched):
//   0000H: JP 0100H   (C3 00 01)  the .COM is loaded at 0100H; a second OCF from 0000H (warm boot) sets `done`
//   0005H: RET        (C9)        BDOS entry: when its OCF starts, the stub does the BDOS call (below), then RET runs
//   0006H: 00H, 0007H: FEH        top of memory = FE00H (the 8080 lesson: zexdoc does LD SP,(0006H))
// BDOS, on an OCF from 0005H: C = 2: con_char = E, one con_strobe pulse. C = 9: the string at DE up to '$', one char per
// two clocks (strobe high one clock, low one clock). Another BDOS call while a string is running is held with WAIT
// until the string is out. Other C values are ignored. Registers are read through the hierarchy (not a pin).
/* verilator lint_off DECLFILENAME */
module z80_system #(
    parameter MEM_INIT = "",
    parameter IO_INIT  = "",
    parameter CPM      = 1
) (
    input  wire        clk,
    input  wire        reset_n,
    input  wire        wait_n,
    input  wire        int_n,
    input  wire        nmi_n,
    input  wire        busrq_n,
    input  wire [7:0]  int_vector,
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
    output wire        busak_n,
    output reg         bus_conflict,
    output reg  [7:0]  con_char,
    output reg         con_strobe,
    output reg         done
);
    reg  [7:0] d_in;
    wire [7:0] mem_rdata, io_rdata;
    reg        busy;          // a BDOS string is being printed
    wire       ocf5, ocf0;
    wire       wait_eff = wait_n & ~(CPM != 0 && busy && ocf5);

    z80 u_cpu (
        .clk(clk), .reset_n(reset_n), .wait_n(wait_eff), .int_n(int_n), .nmi_n(nmi_n), .busrq_n(busrq_n),
        .d_in(d_in), .a(a), .d_out(d_out), .d_oe(d_oe), .bus_oe(bus_oe), .m1_n(m1_n), .mreq_n(mreq_n),
        .iorq_n(iorq_n), .rd_n(rd_n), .wr_n(wr_n), .rfsh_n(rfsh_n), .halt_n(halt_n), .busak_n(busak_n)
    );

    // strobes, only while the CPU drives the control pins
    wire mem_rd = bus_oe & ~mreq_n & ~rd_n;
    wire io_rd  = bus_oe & ~iorq_n & ~rd_n & m1_n;
    wire inta   = bus_oe & ~m1_n & ~iorq_n;
    wire mem_wr = bus_oe & ~mreq_n & ~wr_n;
    wire io_wr  = bus_oe & ~iorq_n & ~wr_n;

    z80_mem #(.AW(16), .INIT_FILE(MEM_INIT)) u_mem (.clk(clk), .addr(a), .we(mem_wr), .wdata(d_out), .rdata(mem_rdata));
    z80_mem #(.AW(8),  .INIT_FILE(IO_INIT))  u_io  (.clk(clk), .addr(a[7:0]), .we(io_wr), .wdata(d_out), .rdata(io_rdata));

    // CP/M overlay on memory reads
    reg [7:0] mem_view;
    always @* begin
        mem_view = mem_rdata;
        if (CPM != 0) begin
            case (a)
                16'h0000: mem_view = 8'hC3;
                16'h0001: mem_view = 8'h00;
                16'h0002: mem_view = 8'h01;
                16'h0005: mem_view = 8'hC9;
                16'h0006: mem_view = 8'h00;
                16'h0007: mem_view = 8'hFE;
                default:  ;
            endcase
        end
    end

    always @* begin
        if (inta)        d_in = int_vector;
        else if (mem_rd) d_in = mem_view;
        else if (io_rd)  d_in = io_rdata;
        else             d_in = 8'hFF;
    end

    // an OCF from an address: M1 read strobe of the memory
    wire ocf = mem_rd & ~m1_n;
    assign ocf5 = ocf & (a == 16'h0005);
    assign ocf0 = ocf & (a == 16'h0000);

    // bus conflict: the CPU drives the data bus while the system does
    wire sys_drive = mem_rd | io_rd | inta;

    // BDOS stub registers (hierarchical read of the current bank)
    wire [7:0]  reg_c = u_cpu.u_regs.bc[u_cpu.u_regs.exx][7:0];
    wire [15:0] reg_de = u_cpu.u_regs.de[u_cpu.u_regs.exx];

    reg        fired5, fired0, first0, phase;
    reg [15:0] sptr;
    always @(posedge clk) begin
        con_strobe <= 1'b0;
        if (!reset_n) begin
            bus_conflict <= 1'b0;
            done <= 1'b0;
            fired5 <= 1'b0; fired0 <= 1'b0; first0 <= 1'b0;
            busy <= 1'b0; phase <= 1'b0; sptr <= 16'h0000;
            con_char <= 8'h00;
        end else begin
            if (d_oe && sys_drive) bus_conflict <= 1'b1;

            if (!ocf0) fired0 <= 1'b0;
            else if (!fired0) begin
                fired0 <= 1'b1;
                if (first0) done <= 1'b1; else first0 <= 1'b1;
            end

            if (!ocf5) fired5 <= 1'b0;

            if (busy) begin
                phase <= ~phase;
                if (!phase) begin
                    if (u_mem.mem[sptr] == 8'h24) busy <= 1'b0;
                    else begin
                        con_char <= u_mem.mem[sptr]; con_strobe <= 1'b1; sptr <= sptr + 16'd1;
                    end
                end
            end else if (CPM != 0 && ocf5 && !fired5) begin
                fired5 <= 1'b1;
                if (reg_c == 8'd2) begin
                    con_char <= reg_de[7:0]; con_strobe <= 1'b1;
                end else if (reg_c == 8'd9) begin
                    busy <= 1'b1; phase <= 1'b0; sptr <= reg_de;
                end
            end
        end
    end
endmodule
