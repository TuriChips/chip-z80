// z80_mem: 2^AW-byte test RAM. Combinational read, write on the rising edge.
// Contract: docs/blocks.md section 3. Owner: Ada.
module z80_mem #(
    parameter AW = 16,
    parameter INIT_FILE = ""
) (
    input  wire          clk,
    input  wire [AW-1:0] addr,
    input  wire          we,
    input  wire [7:0]    wdata,
    output wire [7:0]    rdata
);
    reg [7:0] mem [0:(1<<AW)-1];
    integer i;
    initial begin
        for (i = 0; i < (1<<AW); i = i + 1) mem[i] = 8'h00;
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
    end
    always @(posedge clk) if (we) mem[addr] <= wdata;
    assign rdata = mem[addr];
endmodule
