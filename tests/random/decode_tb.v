// Dumps z80_decode for all 2048 {prefix, ir} (Beru, chip-z80#39). Read by tests/random/xcheck_decode.py.
// One line per input: prefix ir specified is_prefix ins pn pn_s s3 plan_type(octal) plan_len(octal)
module decode_tb;
  reg [2:0] prefix; reg [7:0] ir;
  wire d, p, s3; wire [6:0] ins; wire [2:0] pn, pns; wire [17:0] pt, pl;
  z80_decode u(.prefix(prefix), .ir(ir), .specified(d), .is_prefix(p), .ins(ins), .pn(pn), .pn_s(pns), .s3(s3),
               .plan_type(pt), .plan_len(pl));
  integer i;
  initial begin
    for (i = 0; i < 2048; i = i + 1) begin
      {prefix, ir} = i[10:0]; #1;
      $display("%0d %0d %b %b %0d %0d %0d %b %o %o", prefix, ir, d, p, ins, pn, pns, s3, pt, pl);
    end
    $finish;
  end
endmodule
