# Leo: KLayout batch: DEF + sky130_fd_sc_hd GDS -> <top>.gds and layout.png
# Usage: klayout -b -r render.py -rd def=<top>.def -rd gds=<top>.gds -rd png=layout.png -rd top=<top> -rd pdk=$PDK_ROOT/sky130A
import pya, os
tech = pdk + "/libs.tech/klayout/tech"
ly = pya.Layout()
ly.read(pdk + "/libs.ref/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds")
opt = pya.LoadLayoutOptions()
l = opt.lefdef_config
l.map_file = tech + "/sky130A.map"
l.lef_files = [pdk + "/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef", pdk + "/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"]
l.macro_resolution_mode = 1   # use cells already loaded from GDS, not LEF boxes
l.produce_cell_outlines = False
l.produce_blockages = False
l.produce_obstructions = False
l.produce_labels = False
l.produce_pins = True
ly.read(globals()["def"], opt)
tc = ly.cell(top)
keep = {tc.cell_index()} | set(tc.called_cells())
for ci in [c.cell_index() for c in ly.each_cell() if c.cell_index() not in keep]:
    if ly.is_valid_cell_index(ci):
        ly.delete_cell(ci)
ly.write(gds)
lv = pya.LayoutView()
lv.load_layout(gds, True)
lv.load_layer_props(tech + "/sky130A.lyp")
lv.set_config("text-visible", "false")
lv.max_hier()
lv.zoom_fit()
lv.save_image(png, 1600, 1600)
print("cell", tc.name, "bbox", tc.dbbox())
