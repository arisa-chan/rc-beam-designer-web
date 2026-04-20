import air
from air import AirField, AirResponse
from fastapi.responses import Response
from pydantic import BaseModel
import math
import json
import warnings
from datetime import date

from aci318m25 import MaterialProperties
from aci318m25_complete import ACI318M25MemberLibrary
from column_pdf import generate_column_report
from column_manual import generate_column_manual
from aci318m25_column import (
    ACI318M25ColumnDesign, ColumnGeometry, ColumnLoads, ColumnShape, ColumnType,
    LoadCondition, SeismicDesignCategory, FrameSystem, JointBeamElement, JointColumnElement
)
from shared import blueprint_layout

base_aci_lib = ACI318M25MemberLibrary()


# ----------------------------------------------------------------------
# 1. NATIVE AIR SCHEMA
# ----------------------------------------------------------------------
class ColumnDesignModel(BaseModel):
    action: str = AirField(default="view")
    proj_name: str = AirField(default="Typical Column Design")
    proj_loc: str = AirField(default="Manila, PH")
    proj_eng: str = AirField(default="Engr. Doe")
    proj_date: str = AirField(default="")

    shape: str = AirField(default="rectangular")
    column_type: str = AirField(default="tied")
    width: float = AirField(default=500.0)
    depth: float = AirField(default=500.0)
    height: float = AirField(default=3200.0)
    clear_height: float = AirField(default=2800.0)

    sdc: str = AirField(default="D")
    frame_system: str = AirField(default="special")
    pref_main: str = AirField(default="D25")
    pref_tie: str = AirField(default="D12")
    fc_prime: float = AirField(default=28.0)
    fy: float = AirField(default=420.0)
    fyt: float = AirField(default=420.0)

    pu: float = AirField(default=2500.0)
    top_mux: float = AirField(default=150.0)
    top_muy: float = AirField(default=80.0)
    top_vux: float = AirField(default=120.0)
    top_vuy: float = AirField(default=90.0)
    bot_mux: float = AirField(default=180.0)
    bot_muy: float = AirField(default=90.0)
    bot_vux: float = AirField(default=120.0)
    bot_vuy: float = AirField(default=90.0)
    # ACI 318M-25 §6.2.5: M1/M2 ratio for slenderness limit (34 − 12·M1/M2, max 40).
    # Positive = single curvature (conservative, limit → 22 at +1.0).
    # Negative = double curvature (relaxed, limit → 40 at −1.0).
    m1_m2_x: float = AirField(default=1.0)
    m1_m2_y: float = AirField(default=1.0)
    # #5: Effective-length factor k (braced frame ≤ 1.0; sway frame > 1.0, per ACI §6.2.5).
    k_factor: float = AirField(default=1.0)
    # #6: Concrete clear cover (mm); affects bar-spacing and SMF hx checks.
    cover: float = AirField(default=40.0)

    generate_pdf: str = AirField(default="")

    top_bx1_exists: str = AirField(default="yes")
    top_bx1_b: float = AirField(default=300.0)
    top_bx1_d: float = AirField(default=440.0)
    top_bx1_offset: float = AirField(default=0.0)
    top_bx1_qty_top: int = AirField(default=4)
    top_bx1_dia_top: str = AirField(default="D20")
    top_bx1_qty_bot: int = AirField(default=2)
    top_bx1_dia_bot: str = AirField(default="D20")
    # #7: Per-beam materials for correct Mpr / joint shear calculation (JointBeamElement.fc_prime / .fy).
    top_bx1_fc: float = AirField(default=28.0)
    top_bx1_fy: float = AirField(default=420.0)

    top_bx2_exists: str = AirField(default="yes")
    top_bx2_b: float = AirField(default=300.0)
    top_bx2_d: float = AirField(default=440.0)
    top_bx2_offset: float = AirField(default=0.0)
    top_bx2_qty_top: int = AirField(default=4)
    top_bx2_dia_top: str = AirField(default="D20")
    top_bx2_qty_bot: int = AirField(default=2)
    top_bx2_dia_bot: str = AirField(default="D20")
    top_bx2_fc: float = AirField(default=28.0)
    top_bx2_fy: float = AirField(default=420.0)

    top_by1_exists: str = AirField(default="no")
    top_by1_b: float = AirField(default=300.0)
    top_by1_d: float = AirField(default=440.0)
    top_by1_offset: float = AirField(default=0.0)
    top_by1_qty_top: int = AirField(default=4)
    top_by1_dia_top: str = AirField(default="D20")
    top_by1_qty_bot: int = AirField(default=2)
    top_by1_dia_bot: str = AirField(default="D20")
    top_by1_fc: float = AirField(default=28.0)
    top_by1_fy: float = AirField(default=420.0)

    top_by2_exists: str = AirField(default="no")
    top_by2_b: float = AirField(default=300.0)
    top_by2_d: float = AirField(default=440.0)
    top_by2_offset: float = AirField(default=0.0)
    top_by2_qty_top: int = AirField(default=4)
    top_by2_dia_top: str = AirField(default="D20")
    top_by2_qty_bot: int = AirField(default=2)
    top_by2_dia_bot: str = AirField(default="D20")
    top_by2_fc: float = AirField(default=28.0)
    top_by2_fy: float = AirField(default=420.0)

    top_ca_exists: str = AirField(default="yes")
    top_ca_b: float = AirField(default=500.0)
    top_ca_h: float = AirField(default=500.0)
    top_ca_qty: int = AirField(default=8)
    top_ca_dia: str = AirField(default="D20")
    top_ca_pu: float = AirField(default=2000.0)


# ----------------------------------------------------------------------
# 2. UI RENDER HELPERS
# ----------------------------------------------------------------------
def generate_column_section_css(width, depth, cover, num_bars, legs_x, legs_y, shape="rectangular", column_type="tied"):
    scale = min(200 / max(width, 1), 200 / max(depth, 1)) if shape == "rectangular" else 200 / max(width, 1)
    draw_w = width * scale
    draw_h = depth * scale if shape == "rectangular" else width * scale
    c_s = cover * scale
    children = []
    core_w, core_h = draw_w - 2 * c_s, draw_h - 2 * c_s

    if core_w > 0 and core_h > 0:
        # Draw Ties
        if shape == "circular":
            if column_type == "spiral":
                # Solid continuous circle for spiral (helix cross-section)
                children.append(air.Div(style=f"position: absolute; left: {c_s}px; top: {c_s}px; width: {core_w}px; height: {core_h}px; border: 3px solid #db2777; border-radius: 50%; box-sizing: border-box;"))
            else:
                children.append(air.Div(style=f"position: absolute; left: {c_s}px; top: {c_s}px; width: {core_w}px; height: {core_h}px; border: 2px dashed #db2777; border-radius: 50%; box-sizing: border-box;"))
        else:
            children.append(air.Div(
                style=f"position: absolute; left: {c_s}px; top: {c_s}px; width: {core_w}px; height: {core_h}px; border: 2px dashed #db2777; border-radius: 4px; box-sizing: border-box;"))
            if legs_x > 2:
                spacing_x = core_w / (legs_x - 1)
                for i in range(1, legs_x - 1): children.append(air.Div(
                    style=f"position: absolute; left: {c_s + i * spacing_x}px; top: {c_s}px; width: 0px; height: {core_h}px; border-left: 2px dashed #db2777; box-sizing: border-box;"))
            if legs_y > 2:
                spacing_y = core_h / (legs_y - 1)
                for i in range(1, legs_y - 1): children.append(air.Div(
                    style=f"position: absolute; left: {c_s}px; top: {c_s + i * spacing_y}px; width: {core_w}px; height: 0px; border-top: 2px dashed #db2777; box-sizing: border-box;"))

    # INSET OFFSET: Pushes main bars inside the tie boundary for realistic overlap prevention
    inset = 4
    bx, by = c_s + inset, c_s + inset
    bw, bh = core_w - 2 * inset, core_h - 2 * inset

    def add_bar(x, y):
        children.append(air.Div(
            style=f"position: absolute; left: {x - 6}px; top: {y - 6}px; width: 12px; height: 12px; background: #2563eb; border: 2px solid #111827; border-radius: 50%; box-sizing: border-box;"))

    if shape == "circular":
        import math
        Rc = bw / 2.0
        center_x = draw_w / 2.0
        center_y = draw_h / 2.0
        for i in range(num_bars):
            theta = i * (2 * math.pi / max(1, num_bars))
            add_bar(center_x + Rc * math.cos(theta), center_y + Rc * math.sin(theta))
    else:
        nx_face, ny_face = 0, 0
        if num_bars > 4:
            rem = num_bars - 4
            ratio = width / (width + depth) if (width + depth) > 0 else 0.5
            nx_inter = 2 * int(round(rem * ratio / 2.0))
            nx_face, ny_face = nx_inter // 2, (rem - nx_inter) // 2

        if bw >= 0 and bh >= 0:
            add_bar(bx, by);
            add_bar(bx + bw, by);
            add_bar(bx, by + bh);
            add_bar(bx + bw, by + bh)
            if nx_face > 0:
                sp_x = bw / (nx_face + 1)
                for i in range(1, nx_face + 1): add_bar(bx + i * sp_x, by); add_bar(bx + i * sp_x, by + bh)
            if ny_face > 0:
                sp_y = bh / (ny_face + 1)
                for i in range(1, ny_face + 1): add_bar(bx, by + i * sp_y); add_bar(bx + bw, by + i * sp_y)

    radius_style = "border-radius: 50%;" if shape == "circular" else "border-radius: 4px;"
    overflow_style = "overflow: hidden;" if shape == "circular" else ""
    concrete_block = air.Div(*children,
                             style=f"position: relative; width: {draw_w}px; height: {draw_h}px; background: var(--bg-elevated); border: 3px solid var(--text-primary); {radius_style} {overflow_style} box-sizing: border-box; margin: 0 auto;")
    return air.Div(
        air.Div(f"Diameter {width} mm" if shape == "circular" else f"{width} mm",
                style="text-align: center; font-family: monospace; font-weight: 700; color: var(--text-muted); margin-bottom: 8px;"),
        air.Div(air.Div(f"{depth} mm" if shape == "rectangular" else "",
                        style="position: absolute; left: -65px; top: 50%; transform: translateY(-50%); font-family: monospace; font-weight: 700; color: var(--text-muted);"),
                concrete_block, style="position: relative; display: inline-block; margin-left: 40px;"),
        style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border); width: 100%; box-sizing: border-box;"
    )


def generate_column_elevation_css(height, clear_height, max_dim, s_hinge, s_mid, shape="rectangular", column_type="tied"):
    lo = max(max_dim, clear_height / 6.0, 450.0) if s_hinge != s_mid else 0.0
    if lo * 2 >= clear_height: lo = clear_height / 2.0

    vis_height = 280
    vis_width = 80
    scale = vis_height / height

    children = []

    # Vertical Main Bars (3 lines representation)
    children.append(air.Div(
        style="position: absolute; left: 15%; top: -5px; bottom: -5px; width: 4px; background: #2563eb; border-radius: 2px; z-index: 2;"))
    children.append(air.Div(
        style="position: absolute; left: 50%; top: -5px; bottom: -5px; width: 4px; background: #2563eb; border-radius: 2px; transform: translateX(-50%); z-index: 2;"))
    children.append(air.Div(
        style="position: absolute; right: 15%; top: -5px; bottom: -5px; width: 4px; background: #2563eb; border-radius: 2px; z-index: 2;"))

    # Horizontal Ties / Spiral zigzag
    y = 50.0
    loop_guard = 0
    if shape == "circular" and column_type == "spiral":
        going_right = True
        while y <= height - 50.0 and loop_guard < 300:
            loop_guard += 1
            is_hinge = (y <= lo) or (y >= height - lo)
            current_s = s_hinge if is_hinge else s_mid
            color = "#db2777" if is_hinge else "#9ca3af"
            y_end = min(y + current_s, height - 50.0)
            y_px = y * scale
            h_px = (y_end - y) * scale
            if going_right:
                gradient = f"linear-gradient(to top right, transparent calc(50% - 1px), {color} calc(50% - 1px), {color} calc(50% + 1px), transparent calc(50% + 1px))"
            else:
                gradient = f"linear-gradient(to top left, transparent calc(50% - 1px), {color} calc(50% - 1px), {color} calc(50% + 1px), transparent calc(50% + 1px))"
            if h_px > 0:
                children.append(air.Div(
                    style=f"position: absolute; bottom: {y_px:.1f}px; left: 5%; right: 5%; height: {h_px:.1f}px; background: {gradient}; z-index: 1;"))
            going_right = not going_right
            y += current_s
    else:
        while y <= height - 50.0 and loop_guard < 300:
            loop_guard += 1
            is_hinge = (y <= lo) or (y >= height - lo)
            current_s = s_hinge if is_hinge else s_mid
            color = "#db2777" if is_hinge else "#9ca3af"
            children.append(air.Div(
                style=f"position: absolute; bottom: {y * scale}px; left: 5%; right: 5%; height: 2px; background: {color}; z-index: 1;"))
            y += current_s

    # Confinement Zone Dimension Labels
    labels = []
    if lo > 0:
        lo_px = lo * scale
        labels.append(air.Div(f"lo ({lo:.0f} mm)",
                              style=f"position: absolute; right: -90px; bottom: 0; height: {lo_px}px; display: flex; align-items: center; font-size: 11px; color: #db2777; font-weight: bold; border-left: 2px solid #db2777; padding-left: 6px;"))
        labels.append(air.Div(f"Midheight",
                              style=f"position: absolute; right: -90px; bottom: {lo_px}px; top: {lo_px}px; display: flex; align-items: center; font-size: 11px; color: #6b7280; border-left: 2px dashed #9ca3af; padding-left: 6px;"))
        labels.append(air.Div(f"lo ({lo:.0f} mm)",
                              style=f"position: absolute; right: -90px; top: 0; height: {lo_px}px; display: flex; align-items: center; font-size: 11px; color: #db2777; font-weight: bold; border-left: 2px solid #db2777; padding-left: 6px;"))

    concrete_block = air.Div(*children, *labels,
                             style=f"position: relative; width: {vis_width}px; height: {vis_height}px; background: var(--bg-elevated); border: 2px solid var(--text-primary); border-radius: 2px; box-sizing: border-box; margin: 0 auto;")
    return air.Div(
        concrete_block,
        air.Div(f"Elevation (H = {height} mm)",
                style="text-align: center; font-family: monospace; font-weight: 700; color: var(--text-muted); margin-top: 12px;"),
        style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px 100px 16px 16px; background: var(--bg-card); border-radius: 8px; border: 1px solid var(--border); width: 100%; box-sizing: border-box;"
    )


def render_top_joint_modal(modal_id, data):
    modal_style = "display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.6);"
    content_style = "background-color: var(--bg-card); margin: 5% auto; padding: 24px; border: 1px solid var(--border); width: 95%; max-width: 800px; border-radius: 8px; position: relative;"
    bar_opts = ["D16", "D20", "D25", "D28", "D32", "D36"]

    def render_element_block(title, prefix, is_col=False):
        exists_val = getattr(data, f"{prefix}_exists")
        display_style = "block" if exists_val == "yes" else "none"
        js_func = f"document.getElementById('{prefix}_fields').style.display = this.value === 'yes' ? 'block' : 'none';"

        if is_col:
            fields = [
                air.Div(air.Label("Dimension along x (mm)"),
                        air.Input(type="number", name=f"{prefix}_b", value=str(getattr(data, f"{prefix}_b")),
                                  step="any"), class_="form-group"),
                air.Div(air.Label("Dimension along y (mm)"),
                        air.Input(type="number", name=f"{prefix}_h", value=str(getattr(data, f"{prefix}_h")),
                                  step="any"), class_="form-group"),
                air.Div(
                    air.Div(air.Label("Number of vertical bars"),
                            air.Input(type="number", name=f"{prefix}_qty", value=str(getattr(data, f"{prefix}_qty")),
                                      step="1"), class_="form-group"),
                    air.Div(air.Label("Vertical bar diameter"), air.Select(
                        *[air.Option(opt, selected=(getattr(data, f"{prefix}_dia") == opt)) for opt in bar_opts],
                        name=f"{prefix}_dia"), class_="form-group"),
                    class_="grid-2"
                ),
                air.Div(air.Label("Factored axial Pu (kN)"),
                        air.Input(type="number", name=f"{prefix}_pu", value=str(getattr(data, f"{prefix}_pu")),
                                  step="any"), class_="form-group")
            ]
        else:
            fields = [
                air.Div(air.Label("Beam width (mm)"),
                        air.Input(type="number", name=f"{prefix}_b", value=str(getattr(data, f"{prefix}_b")),
                                  step="any"), class_="form-group"),
                air.Div(air.Label("Beam effective depth (mm)"),
                        air.Input(type="number", name=f"{prefix}_d", value=str(getattr(data, f"{prefix}_d")),
                                  step="any"), class_="form-group"),
                air.Div(air.Label("Offset from column centerline (mm)"),
                        air.Input(type="number", name=f"{prefix}_offset",
                                  value=str(getattr(data, f"{prefix}_offset", 0.0)),
                                  step="any"), class_="form-group"),
                air.Div(
                    air.Div(air.Label("Number of top bars"), air.Input(type="number", name=f"{prefix}_qty_top",
                                                                 value=str(getattr(data, f"{prefix}_qty_top")),
                                                                 step="1"), class_="form-group"),
                    air.Div(air.Label("Top bar diameter"), air.Select(
                        *[air.Option(opt, selected=(getattr(data, f"{prefix}_dia_top") == opt)) for opt in bar_opts],
                        name=f"{prefix}_dia_top"), class_="form-group"),
                    class_="grid-2"
                ),
                air.Div(
                    air.Div(air.Label("Number of bottom bars"), air.Input(type="number", name=f"{prefix}_qty_bot",
                                                                 value=str(getattr(data, f"{prefix}_qty_bot")),
                                                                 step="1"), class_="form-group"),
                    air.Div(air.Label("Bottom bar diameter"), air.Select(
                        *[air.Option(opt, selected=(getattr(data, f"{prefix}_dia_bot") == opt)) for opt in bar_opts],
                        name=f"{prefix}_dia_bot"), class_="form-group"),
                    class_="grid-2"
                ),
                air.Div(
                    air.Div(air.Label("Beam f\u2019c (MPa)"),
                            air.Input(type="number", name=f"{prefix}_fc",
                                      value=str(getattr(data, f"{prefix}_fc", 28.0)),
                                      step="any", min="14"), class_="form-group"),
                    air.Div(air.Label("Beam fy (MPa)"),
                            air.Input(type="number", name=f"{prefix}_fy",
                                      value=str(getattr(data, f"{prefix}_fy", 420.0)),
                                      step="any", min="280"), class_="form-group"),
                    class_="grid-2"
                )
            ]
        return air.Div(
            air.H4(title, style="margin-bottom: 12px; color: var(--text-secondary); font-size: 15px;"),
            air.Div(air.Label("Is element present?"),
                    air.Select(air.Option("Yes", value="yes", selected=exists_val == "yes"),
                               air.Option("No", value="no", selected=exists_val == "no"), name=f"{prefix}_exists",
                               onchange=js_func), class_="form-group"),
            air.Div(*fields, id=f"{prefix}_fields", style=f"display: {display_style};"),
            class_="section-box"
        )

    return air.Div(
        air.Div(
            air.Span("×",
                     style="color: var(--text-muted); position: absolute; right: 20px; top: 15px; font-size: 28px; font-weight: bold; cursor: pointer;",
                     onclick=f"document.getElementById('{modal_id}').style.display='none'"),
            air.H3("Seismic Joint Checks", style="margin-bottom: 16px; color: var(--cyan);"),
            air.H4("Framing along x-direction",
                   style="border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px;"),
            air.Div(render_element_block("Left beam", "top_bx1"), render_element_block("Right beam", "top_bx2"),
                    class_="grid-2", style="margin-bottom: 24px;"),
            air.H4("Framing along y-direction",
                   style="border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px;"),
            air.Div(render_element_block("Left beam", "top_by1"), render_element_block("Right beam", "top_by2"),
                    class_="grid-2", style="margin-bottom: 24px;"),
            air.H4("Column above",
                   style="border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 16px;"),
            render_element_block("Column above", "top_ca", is_col=True),
            air.Button("Save & Close", type="button",
                       onclick=f"document.getElementById('{modal_id}').style.display='none'",
                       style="width: 100%; margin-top: 16px; background-color: #10b981; border: none;"),
            style=content_style
        ), id=modal_id, style=modal_style
    )


def build_scwb_element(d_res, title):
    if not d_res.exists:
        return air.Div(air.H5(title, style="margin-bottom: 8px; color: var(--text-secondary); font-size: 15px;"),
                       air.P("No beams defined.", style="font-size: 13px; color: var(--text-muted);"))
    return air.Div(
        air.H5(title, style="margin-bottom: 8px; color: var(--text-secondary); font-size: 15px;"),
        air.Ul(
            air.Li(air.Strong("ΣMnc/ΣMnb"),
                   air.Span(f"{d_res.ratio_scwb:.2f} {'≥' if d_res.ratio_scwb >= 1.2 else '<'} 1.2",
                            class_=f"status-badge {'pass' if d_res.ratio_scwb >= 1.2 else 'fail'}")),
            air.Li(air.Strong("Factored shear Vj"), air.Span(f"{d_res.vj_u:.1f} kN", class_="data-value")),
            air.Li(air.Strong("Joint capacity ɸVnj"), air.Span(f"{d_res.phi_vj:.1f} kN", class_="data-value")),
            air.Li(air.Strong("Joint shear DCR"),
                   air.Span(f"{d_res.ratio_vj:.2f} {'≤' if d_res.ratio_vj <= 1.0 else '>'} 1.00",
                            class_=f"status-badge {'pass' if d_res.ratio_vj <= 1.0 else 'fail'}"))
        )
    )


# ── Column Module Extra CSS ──────────────────────────────────────────────
COLUMN_EXTRA_CSS = """<style>
.col-tab-nav {
    display: flex; gap: 0; margin-bottom: 0;
    border-bottom: 2px solid var(--border);
    overflow-x: auto; scrollbar-width: none; -webkit-overflow-scrolling: touch;
}
.col-tab-nav::-webkit-scrollbar { display: none; }
.col-tab-btn {
    font-family: 'Space Mono', monospace; font-size: 10px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase; padding: 12px 20px;
    border: none; background: transparent; color: var(--text-muted);
    cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px;
    transition: color 0.2s, border-color 0.2s, background 0.2s;
    white-space: nowrap; flex-shrink: 0;
}
.col-tab-btn:hover {
    color: var(--text-primary); background: var(--accent-glow);
    transform: none; box-shadow: none; border-bottom-color: var(--border-light);
}
.col-tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); background: transparent; }
.col-tab-panel { display: none; padding-top: 24px; }
.col-tab-panel.active { display: block; }
.col-canvas-box {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 20px 12px 12px; background: var(--bg-surface);
    border: 1px solid var(--border); border-radius: var(--radius); min-height: 300px; gap: 8px;
}
.col-canvas-box canvas { display: block; max-width: 100%; }
.col-canvas-legend { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
.col-legend-item {
    display: flex; align-items: center; gap: 5px;
    font-family: 'Space Mono', monospace; font-size: 9px;
    color: var(--text-muted); letter-spacing: 0.08em; text-transform: uppercase;
}
.col-legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.col-field-wrap { position: relative; }
.col-field-wrap input { padding-right: 48px; }
.col-field-unit {
    position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
    font-family: 'Space Mono', monospace; font-size: 9px;
    color: var(--text-muted); pointer-events: none; user-select: none;
}
.col-hint {
    display: block; margin-top: 3px;
    font-family: 'Space Mono', monospace; font-size: 9px;
    color: var(--text-muted); letter-spacing: 0.06em;
}
.col-tab-footer {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border);
}
.col-tab-footer .btn-back {
    background: transparent; color: var(--text-muted);
    border: 1px solid var(--border); font-size: 14px; padding: 10px 20px;
    letter-spacing: 0.08em;
}
.col-tab-footer .btn-back:hover {
    color: var(--text-primary); border-color: var(--border-light);
    transform: none; box-shadow: none;
}
.col-tab-footer .btn-next {
    background: var(--cyan); color: var(--bg-deep);
    font-size: 14px; padding: 10px 24px; letter-spacing: 0.08em;
}
.col-tab-footer .btn-next:hover { background: var(--cyan-dim); transform: translateY(-1px); }
.col-run-sticky {
    position: fixed; bottom: 24px; right: 24px; z-index: 999;
}
.col-run-btn {
    background: var(--accent); color: var(--bg-deep);
    font-family: 'Bebas Neue', sans-serif; font-size: 20px;
    letter-spacing: 0.12em; padding: 14px 40px;
    border: none; border-radius: var(--radius); cursor: pointer;
    box-shadow: 0 4px 24px rgba(245,158,11,0.45);
    transition: all 0.2s; line-height: 1;
}
.col-run-btn:hover {
    background: var(--accent-dim); transform: translateY(-2px);
    box-shadow: 0 8px 32px rgba(245,158,11,0.55);
}
.curvature-hint-wrap {
    display: flex; gap: 24px; justify-content: center; align-items: flex-start;
    flex-wrap: wrap; margin: 8px 0 16px;
}
.curvature-item {
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    font-family: 'Space Mono', monospace; font-size: 9px;
    color: var(--text-muted); letter-spacing: 0.06em; text-transform: uppercase;
}
.col-joint-section { border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.col-joint-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px; background: var(--bg-elevated); cursor: pointer;
    font-family: 'Space Mono', monospace; font-size: 10px;
    font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--cyan); transition: background 0.2s; user-select: none;
    border: none; width: 100%; text-align: left;
}
.col-joint-header:hover { background: rgba(6,182,212,0.1); transform: none; box-shadow: none; }
.col-joint-header .jh-arrow { transition: transform 0.25s; font-style: normal; }
.col-joint-header.open .jh-arrow { transform: rotate(90deg); }
.col-joint-body { padding: 16px; background: var(--bg-card); }
.col-section-divider {
    font-family: 'Space Mono', monospace; font-size: 9px; font-weight: 700;
    letter-spacing: 0.15em; text-transform: uppercase; color: var(--text-muted);
    border-bottom: 1px solid var(--border); padding-bottom: 6px; margin: 20px 0 14px;
}
.col-pu-input input {
    font-size: 22px; font-family: 'Bebas Neue', sans-serif;
    letter-spacing: 0.08em; text-align: center; padding: 14px 60px 14px 16px;
}
.col-load-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px;
}
@media (max-width: 900px) { .col-load-grid { grid-template-columns: 1fr; } }
@media (max-width: 900px) { .col-run-sticky { bottom: 16px; right: 16px; } }
@media print { .col-run-sticky { display: none; } }
</style>"""

# ── Column Module Extra JS ───────────────────────────────────────────────
COLUMN_EXTRA_JS = """<script>
function colShowTab(id) {
    document.querySelectorAll('.col-tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.col-tab-btn').forEach(b => b.classList.remove('active'));
    var panel = document.getElementById('col-panel-' + id);
    var btn   = document.getElementById('col-tab-' + id);
    if (panel) panel.classList.add('active');
    if (btn)   btn.classList.add('active');
    if (id === 'section') { setTimeout(drawSectionCanvas, 30); }
    if (id === 'loads')   { setTimeout(drawLoadCanvas, 30); }
}

function isDark() {
    return !document.documentElement.classList.contains('light-mode');
}

/* ─── Cross-section canvas ─────────────────────────── */
function drawSectionCanvas() {
    var canvas = document.getElementById('col-section-canvas');
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    var dark = isDark();

    var shapeEl = document.querySelector('[name="shape"]');
    var widthEl = document.querySelector('[name="width"]');
    var depthEl = document.querySelector('[name="depth"]');
    var coverEl = document.querySelector('[name="cover"]');
    var typeEl  = document.querySelector('[name="column_type"]');
    if (!shapeEl || !widthEl || !coverEl) return;

    var shape   = shapeEl.value;
    var width   = Math.max(parseFloat(widthEl.value) || 500, 100);
    var depth   = (shape === 'circular') ? width : Math.max(parseFloat(depthEl ? depthEl.value : 500) || 500, 100);
    var cover   = Math.min(parseFloat(coverEl.value) || 40, Math.min(width, depth) * 0.3);
    var isSpiral = typeEl && typeEl.value === 'spiral';

    var W = 280, H = 280;
    canvas.width = W; canvas.height = H;
    ctx.clearRect(0, 0, W, H);

    var scale = Math.min((W - 64) / width, (H - 64) / depth);
    var dw = width * scale, dh = depth * scale;
    var ox = (W - dw) / 2, oy = (H - dh) / 2;
    var cs = cover * scale;

    /* colours */
    var cConcrete = dark ? '#334155' : '#cbd5e1';
    var cOutline  = dark ? '#f1f5f9' : '#0f172a';
    var cTie      = '#db2777';
    var cBar      = '#2563eb';
    var cBarEdge  = dark ? '#0f172a' : '#ffffff';
    var cDim      = dark ? '#f59e0b' : '#b45309';

    /* concrete body */
    ctx.fillStyle = cConcrete;
    ctx.strokeStyle = cOutline;
    ctx.lineWidth = 3;
    ctx.beginPath();
    if (shape === 'circular') {
        ctx.arc(W/2, H/2, dw/2, 0, Math.PI*2);
    } else {
        ctx.rect(ox, oy, dw, dh);
    }
    ctx.fill(); ctx.stroke();

    /* tie / spiral */
    ctx.strokeStyle = cTie;
    ctx.lineWidth = isSpiral && shape === 'circular' ? 2.5 : 1.5;
    if (!isSpiral) ctx.setLineDash([4, 3]);
    ctx.beginPath();
    if (shape === 'circular') {
        ctx.arc(W/2, H/2, dw/2 - cs, 0, Math.PI*2);
    } else {
        ctx.rect(ox + cs, oy + cs, dw - 2*cs, dh - 2*cs);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    /* representative bars (8 bars, illustrative) */
    var nBars = 8;
    var inset = cs + 6;
    var bw = dw - 2*inset, bh = dh - 2*inset;

    function drawBar(bx, by) {
        ctx.fillStyle = cBar; ctx.strokeStyle = cBarEdge; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(bx, by, 6, 0, Math.PI*2); ctx.fill(); ctx.stroke();
    }

    if (shape === 'circular') {
        var R = dw/2 - inset;
        for (var i = 0; i < nBars; i++) {
            var a = (i / nBars) * Math.PI * 2 - Math.PI/2;
            drawBar(W/2 + R * Math.cos(a), H/2 + R * Math.sin(a));
        }
    } else if (bw > 0 && bh > 0) {
        var rem = nBars - 4;
        var ratio = width / (width + depth);
        var nxf = Math.max(0, Math.round(rem * ratio / 2));
        var nyf = Math.max(0, Math.floor((rem - 2*nxf) / 2));
        var bars = [
            [ox+inset, oy+inset], [ox+inset+bw, oy+inset],
            [ox+inset, oy+inset+bh], [ox+inset+bw, oy+inset+bh]
        ];
        for (var j = 1; j <= nxf; j++) {
            bars.push([ox+inset + j*bw/(nxf+1), oy+inset]);
            bars.push([ox+inset + j*bw/(nxf+1), oy+inset+bh]);
        }
        for (var j = 1; j <= nyf; j++) {
            bars.push([ox+inset, oy+inset + j*bh/(nyf+1)]);
            bars.push([ox+inset+bw, oy+inset + j*bh/(nyf+1)]);
        }
        bars.forEach(function(p) { drawBar(p[0], p[1]); });
    }

    /* dimension annotations */
    ctx.font = 'bold 11px JetBrains Mono, monospace';
    ctx.fillStyle = cDim;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var wLbl = (shape === 'circular' ? '\\u00d8' : '') + width.toFixed(0) + ' mm';
    ctx.fillText(wLbl, ox + dw/2, oy + dh + 20);
    if (shape !== 'circular') {
        ctx.save();
        ctx.translate(ox - 22, oy + dh/2);
        ctx.rotate(-Math.PI/2);
        ctx.fillText(depth.toFixed(0) + ' mm', 0, 0);
        ctx.restore();
    }
    /* cover dim tick */
    if (cs > 5 && shape !== 'circular') {
        ctx.strokeStyle = cDim; ctx.lineWidth = 0.75; ctx.globalAlpha = 0.55;
        ctx.setLineDash([2,2]);
        ctx.beginPath(); ctx.moveTo(ox, oy-6); ctx.lineTo(ox+cs, oy-6); ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 0.7;
        ctx.font = '9px JetBrains Mono, monospace';
        ctx.fillStyle = cDim; ctx.textAlign = 'center';
        ctx.fillText('cc ' + cover.toFixed(0), ox + cs/2, oy - 15);
        ctx.globalAlpha = 1.0;
    }
}

/* ─── Load diagram canvas ──────────────────────────── */
function drawLoadCanvas() {
    var canvas = document.getElementById('col-load-canvas');
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    var dark = isDark();
    var W = 320, H = 380;
    canvas.width = W; canvas.height = H;
    ctx.clearRect(0, 0, W, H);

    function gv(name) {
        var el = document.querySelector('[name="' + name + '"]');
        return el ? (parseFloat(el.value) || 0) : 0;
    }
    var pu     = gv('pu');
    var tMux   = gv('top_mux'),  tMuy = gv('top_muy');
    var tVux   = gv('top_vux'),  tVuy = gv('top_vuy');
    var bMux   = gv('bot_mux'),  bMuy = gv('bot_muy');
    var bVux   = gv('bot_vux'),  bVuy = gv('bot_vuy');

    var allM   = Math.max(Math.abs(tMux), Math.abs(tMuy), Math.abs(bMux), Math.abs(bMuy), 1);
    var allV   = Math.max(Math.abs(tVux), Math.abs(tVuy), Math.abs(bVux), Math.abs(bVuy), 1);

    var cText  = dark ? '#f1f5f9' : '#0f172a';
    var cMuted = dark ? '#94a3b8' : '#64748b';
    var cConc  = dark ? '#334155' : '#cbd5e1';
    var cAxial = '#ef4444';
    var cMom   = '#8b5cf6';
    var cShear = '#06b6d4';

    /* column body */
    var cW = 46, cH = 220, cx = W/2, cy = H/2;
    var cl = cx - cW/2, ct = cy - cH/2;
    ctx.fillStyle = cConc; ctx.strokeStyle = cText; ctx.lineWidth = 2;
    ctx.fillRect(cl, ct, cW, cH); ctx.strokeRect(cl, ct, cW, cH);
    /* vertical bar lines */
    ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 2;
    [cl+7, cx, cl+cW-7].forEach(function(x) {
        ctx.beginPath(); ctx.moveTo(x, ct-4); ctx.lineTo(x, ct+cH+4); ctx.stroke();
    });

    /* helper: filled arrow */
    function arrow(x1, y1, x2, y2, color, lw) {
        lw = lw || 2;
        var dx = x2-x1, dy = y2-y1;
        var len = Math.sqrt(dx*dx+dy*dy);
        if (len < 3) return;
        var ang = Math.atan2(dy, dx);
        ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
        var as = 9;
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - as*Math.cos(ang-0.4), y2 - as*Math.sin(ang-0.4));
        ctx.lineTo(x2 - as*Math.cos(ang+0.4), y2 - as*Math.sin(ang+0.4));
        ctx.closePath(); ctx.fill();
    }

    /* helper: moment arc arrow */
    function momentArc(cx2, cy2, r, startA, sweepA, color, lw) {
        lw = lw || 2;
        ctx.strokeStyle = color; ctx.lineWidth = lw;
        ctx.beginPath();
        ctx.arc(cx2, cy2, r, startA, startA+sweepA, sweepA < 0);
        ctx.stroke();
        var endA = startA + sweepA;
        var tx = cx2 + r*Math.cos(endA), ty = cy2 + r*Math.sin(endA);
        var tang = endA + (sweepA > 0 ? Math.PI/2 : -Math.PI/2);
        var as = 8;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(tx - as*Math.cos(tang-0.4), ty - as*Math.sin(tang-0.4));
        ctx.lineTo(tx - as*Math.cos(tang+0.4), ty - as*Math.sin(tang+0.4));
        ctx.closePath(); ctx.fill();
    }

    function lbl(x, y, text, color, size, align) {
        size = size || 9; align = align || 'center';
        ctx.font = 'bold ' + size + 'px JetBrains Mono, monospace';
        ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = 'middle';
        ctx.fillText(text, x, y);
    }

    /* TOP label */
    lbl(cx, ct - 38, 'TOP', cMuted, 9);
    /* Pu downward */
    if (pu > 0) {
        arrow(cx, ct - 60, cx, ct - 2, cAxial, 3);
        lbl(cx, ct - 68, 'Pu = ' + pu.toFixed(0) + ' kN', cAxial, 9);
    }

    /* TOP moments — Mux left side arc, Muy right side arc */
    var mScale = 30; /* fixed arc radius for clarity */
    if (Math.abs(tMux) > 0) {
        var sweep = (tMux > 0 ? 1 : -1) * (Math.PI * 0.8);
        momentArc(cl - 20, ct + 20, 16, -Math.PI/2, sweep, cMom, 2);
        lbl(cl - 40, ct + 20, 'Mux', cMom, 8, 'right');
        lbl(cl - 40, ct + 30, tMux.toFixed(0)+'kN\u00b7m', cMom, 8, 'right');
    }
    if (Math.abs(tMuy) > 0) {
        var sweep = (tMuy > 0 ? -1 : 1) * (Math.PI * 0.8);
        momentArc(cl + cW + 20, ct + 20, 16, -Math.PI/2, sweep, cMom, 2);
        lbl(cl + cW + 42, ct + 20, 'Muy', cMom, 8, 'left');
        lbl(cl + cW + 42, ct + 30, tMuy.toFixed(0)+'kN\u00b7m', cMom, 8, 'left');
    }

    /* TOP shear */
    var vTopScale = Math.max(Math.abs(tVux), Math.abs(tVuy)) / allV * 38 + 8;
    if (Math.abs(tVux) > 0) {
        var dir = tVux > 0 ? 1 : -1;
        arrow(cx, ct + 45, cx + dir * vTopScale, ct + 45, cShear, 2);
        lbl(cx + dir * (vTopScale + 6), ct + 44, 'Vux=' + tVux.toFixed(0), cShear, 8, dir > 0 ? 'left' : 'right');
    }
    if (Math.abs(tVuy) > 0) {
        /* show as ⊙/⊗ dot symbol for out-of-plane */
        ctx.strokeStyle = cShear; ctx.fillStyle = cShear; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(cl - 22, ct + 60, 7, 0, Math.PI*2); ctx.stroke();
        if (tVuy > 0) {
            ctx.beginPath(); ctx.arc(cl - 22, ct + 60, 2.5, 0, Math.PI*2); ctx.fill();
        } else {
            ctx.beginPath();
            ctx.moveTo(cl-26, ct+56); ctx.lineTo(cl-18, ct+64);
            ctx.moveTo(cl-18, ct+56); ctx.lineTo(cl-26, ct+64);
            ctx.stroke();
        }
        lbl(cl - 33, ct + 74, 'Vuy='+tVuy.toFixed(0), cShear, 8, 'center');
    }

    /* MID label */
    ctx.font = '8px JetBrains Mono, monospace';
    ctx.fillStyle = cMuted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    ctx.fillText('MID', cl - 6, cy);

    /* BOTTOM moments */
    if (Math.abs(bMux) > 0) {
        var sweep = (bMux > 0 ? 1 : -1) * (Math.PI * 0.8);
        momentArc(cl - 20, ct + cH - 20, 16, -Math.PI/2, sweep, cMom, 2);
        lbl(cl - 40, ct + cH - 20, 'Mux', cMom, 8, 'right');
        lbl(cl - 40, ct + cH - 10, bMux.toFixed(0)+'kN\u00b7m', cMom, 8, 'right');
    }
    if (Math.abs(bMuy) > 0) {
        var sweep = (bMuy > 0 ? -1 : 1) * (Math.PI * 0.8);
        momentArc(cl + cW + 20, ct + cH - 20, 16, -Math.PI/2, sweep, cMom, 2);
        lbl(cl + cW + 42, ct + cH - 20, 'Muy', cMom, 8, 'left');
        lbl(cl + cW + 42, ct + cH - 10, bMuy.toFixed(0)+'kN\u00b7m', cMom, 8, 'left');
    }

    /* BOTTOM shear */
    if (Math.abs(bVux) > 0) {
        var dir = bVux > 0 ? 1 : -1;
        var sc2 = Math.abs(bVux) / allV * 38 + 8;
        arrow(cx, ct + cH - 45, cx + dir * sc2, ct + cH - 45, cShear, 2);
        lbl(cx + dir * (sc2 + 6), ct + cH - 46, 'Vux=' + bVux.toFixed(0), cShear, 8, dir > 0 ? 'left' : 'right');
    }
    if (Math.abs(bVuy) > 0) {
        ctx.strokeStyle = cShear; ctx.fillStyle = cShear; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(cl - 22, ct + cH - 60, 7, 0, Math.PI*2); ctx.stroke();
        if (bVuy > 0) {
            ctx.beginPath(); ctx.arc(cl - 22, ct + cH - 60, 2.5, 0, Math.PI*2); ctx.fill();
        } else {
            ctx.beginPath();
            ctx.moveTo(cl-26, ct+cH-64); ctx.lineTo(cl-18, ct+cH-56);
            ctx.moveTo(cl-18, ct+cH-64); ctx.lineTo(cl-26, ct+cH-56);
            ctx.stroke();
        }
        lbl(cl - 33, ct + cH - 46, 'Vuy='+bVuy.toFixed(0), cShear, 8, 'center');
    }

    /* BOT label */
    lbl(cx, ct + cH + 14, 'BOT', cMuted, 9);
}

/* ─── Joint tab visibility ──────────────────────────── */
function updateJointTabVisibility() {
    var sdc = document.querySelector('[name="sdc"]');
    var fs  = document.querySelector('[name="frame_system"]');
    var btn = document.getElementById('col-tab-joint');
    if (!sdc || !fs || !btn) return;
    var show = (sdc.value === 'D' || sdc.value === 'E' || sdc.value === 'F') && fs.value === 'special';
    btn.style.display = show ? '' : 'none';
    if (!show) {
        var activePanel = document.querySelector('.col-tab-panel.active');
        if (activePanel && activePanel.id === 'col-panel-joint') { colShowTab('loads'); }
    }
}

function toggleJointAccordion(id) {
    var body = document.getElementById(id + '-body');
    var hdr  = document.getElementById(id + '-hdr');
    if (!body || !hdr) return;
    var open = body.style.display !== 'none';
    body.style.display = open ? 'none' : 'block';
    hdr.classList.toggle('open', !open);
}

function toggleBeamFields(prefix) {
    var sel = document.querySelector('[name="' + prefix + '_exists"]');
    var flds = document.getElementById(prefix + '_fields');
    if (!sel || !flds) return;
    flds.style.display = sel.value === 'yes' ? 'block' : 'none';
}

/* ─── Init ─────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
    drawSectionCanvas();
    drawLoadCanvas();
    updateJointTabVisibility();

    ['width','depth','cover','shape','column_type'].forEach(function(n) {
        var els = document.querySelectorAll('[name="' + n + '"]');
        els.forEach(function(el) {
            el.addEventListener('input',  drawSectionCanvas);
            el.addEventListener('change', drawSectionCanvas);
        });
    });

    ['pu','top_mux','top_muy','top_vux','top_vuy','bot_mux','bot_muy','bot_vux','bot_vuy'].forEach(function(n) {
        var el = document.querySelector('[name="' + n + '"]');
        if (el) el.addEventListener('input', drawLoadCanvas);
    });

    var sdc = document.querySelector('[name="sdc"]');
    var fs  = document.querySelector('[name="frame_system"]');
    if (sdc) sdc.addEventListener('change', updateJointTabVisibility);
    if (fs)  fs.addEventListener('change',  updateJointTabVisibility);

    var themBtn = document.getElementById('themeToggleBtn');
    if (themBtn) themBtn.addEventListener('click', function() {
        setTimeout(function() { drawSectionCanvas(); drawLoadCanvas(); }, 60);
    });
});
</script>"""


# ----------------------------------------------------------------------
# 3. MODULE ROUTES
# ----------------------------------------------------------------------
def setup_column_routes(app):
    @app.get("/column/manual")
    def column_manual_route(request: air.Request):
        pdf_bytes = generate_column_manual()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="rc_column_designer_manual.pdf"'},
        )

    @app.get("/column")
    def column_index(request: air.Request):
        data = ColumnDesignModel(**json.loads(request.cookies.get("col_inputs", "{}"))) if request.cookies.get(
            "col_inputs") else ColumnDesignModel()
        if not data.proj_date: data.proj_date = date.today().strftime("%Y-%m-%d")
        csrf_token = getattr(request.state, "csrf_token", request.cookies.get("csrftoken", "dev_token"))
        bar_opts = ["D10", "D12", "D16", "D20", "D25", "D28", "D32", "D36"]
        tie_opts = ["D10", "D12", "D16", "D20", "D25", "D28", "D32", "D36"]
        joint_applicable = data.sdc in ['D', 'E', 'F'] and data.frame_system == 'special'

        # ── helpers ──────────────────────────────────────────────────────
        def fg(label, name, val, t="number", unit="", hint="", step="any", **kw):
            inp = air.Input(type=t, name=name, value=str(val), step=step, **kw)
            inp_node = air.Div(inp, air.Span(unit, class_="col-field-unit"), class_="col-field-wrap") if unit else inp
            children = [air.Label(label), inp_node]
            if hint:
                children.append(air.Span(hint, class_="col-hint"))
            return air.Div(*children, class_="form-group")

        def sg(label, name, options, sel_val, hint="", **kw):
            opts = [air.Option(o[0], value=o[1], selected=(sel_val == o[1])) for o in options]
            children = [air.Label(label), air.Select(*opts, name=name, **kw)]
            if hint:
                children.append(air.Span(hint, class_="col-hint"))
            return air.Div(*children, class_="form-group")

        def tab_footer(back_id=None, next_id=None):
            l = air.Button("← Back", type="button", class_="btn-back",
                           onclick=f"colShowTab('{back_id}')") if back_id else air.Span("")
            r = air.Button("Next →", type="button", class_="btn-next",
                           onclick=f"colShowTab('{next_id}')") if next_id else air.Span("")
            return air.Div(l, r, class_="col-tab-footer")

        # ── curvature hint SVGs ──────────────────────────────────────────
        def curvature_svg(double=False):
            # Simple line drawing: column axis with deflected shape
            path = "M 20 10 Q 35 50 20 90" if not double else "M 20 10 Q 35 35 20 50 Q 5 65 20 90"
            label = "Double curvature\n(M₁/M₂ negative)" if double else "Single curvature\n(M₁/M₂ positive)"
            color = "#10b981" if double else "#f59e0b"
            return air.Div(
                air.Raw(f'<svg width="40" height="100" xmlns="http://www.w3.org/2000/svg">'
                        f'<line x1="20" y1="5" x2="20" y2="95" stroke="#475569" stroke-width="1" stroke-dasharray="3,3"/>'
                        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round"/>'
                        f'<circle cx="20" cy="10" r="3" fill="{color}"/>'
                        f'<circle cx="20" cy="90" r="3" fill="{color}"/>'
                        f'</svg>'),
                air.Span("Single curve" if not double else "Double curve",
                         style=f"font-size:9px; color:{color};"),
                class_="curvature-item"
            )

        # ── joint element block (inline, no modal) ───────────────────────
        def joint_element_block(title, prefix, acc_id, is_col=False):
            exists_val = getattr(data, f"{prefix}_exists")
            fld_display = "block" if exists_val == "yes" else "none"
            bar_j = ["D16", "D20", "D25", "D28", "D32", "D36"]
            onchg = f"toggleBeamFields('{prefix}')"
            if is_col:
                fields_content = [
                    air.Div(
                        fg("b — dimension along x", f"{prefix}_b", getattr(data, f"{prefix}_b"), unit="mm"),
                        fg("h — dimension along y", f"{prefix}_h", getattr(data, f"{prefix}_h"), unit="mm"),
                        class_="grid-2"
                    ),
                    air.Div(
                        fg("Vertical bars", f"{prefix}_qty", getattr(data, f"{prefix}_qty"), t="number", step="1"),
                        sg("Bar diameter", f"{prefix}_dia",
                           [(o, o) for o in bar_j], getattr(data, f"{prefix}_dia")),
                        class_="grid-2"
                    ),
                    fg("Factored axial Pu", f"{prefix}_pu", getattr(data, f"{prefix}_pu"), unit="kN"),
                ]
            else:
                fields_content = [
                    air.Div(
                        fg("Beam width b", f"{prefix}_b", getattr(data, f"{prefix}_b"), unit="mm"),
                        fg("Effective depth d", f"{prefix}_d", getattr(data, f"{prefix}_d"), unit="mm"),
                        class_="grid-2"
                    ),
                    fg("Centerline offset", f"{prefix}_offset",
                       getattr(data, f"{prefix}_offset", 0.0), unit="mm",
                       hint="Positive if beam is offset from column center"),
                    air.Div(
                        fg("Top bars", f"{prefix}_qty_top", getattr(data, f"{prefix}_qty_top"), t="number", step="1"),
                        sg("Top bar size", f"{prefix}_dia_top",
                           [(o, o) for o in bar_j], getattr(data, f"{prefix}_dia_top")),
                        class_="grid-2"
                    ),
                    air.Div(
                        fg("Bottom bars", f"{prefix}_qty_bot", getattr(data, f"{prefix}_qty_bot"), t="number", step="1"),
                        sg("Bottom bar size", f"{prefix}_dia_bot",
                           [(o, o) for o in bar_j], getattr(data, f"{prefix}_dia_bot")),
                        class_="grid-2"
                    ),
                    air.Div(
                        fg("Beam f\u2019c", f"{prefix}_fc",
                           getattr(data, f"{prefix}_fc", 28.0), unit="MPa", min="14"),
                        fg("Beam fy", f"{prefix}_fy",
                           getattr(data, f"{prefix}_fy", 420.0), unit="MPa", min="280"),
                        class_="grid-2"
                    ),
                ]
            is_open = exists_val == "yes"
            hdr_class = "col-joint-header open" if is_open else "col-joint-header"
            body_display = "block" if is_open else "none"
            return air.Div(
                air.Button(
                    title,
                    air.Span("▶", class_="jh-arrow", style="margin-left:auto; font-size:12px;"),
                    type="button",
                    class_=hdr_class,
                    id=f"{acc_id}-hdr",
                    onclick=f"toggleJointAccordion('{acc_id}')",
                    style="display:flex; align-items:center; gap:8px; width:100%;"
                ),
                air.Div(
                    sg("Element present?", f"{prefix}_exists",
                       [("Yes", "yes"), ("No", "no")], exists_val,
                       onchange=onchg),
                    air.Div(*fields_content, id=f"{prefix}_fields",
                            style=f"display:{fld_display};"),
                    id=f"{acc_id}-body",
                    class_="col-joint-body",
                    style=f"display:{body_display};"
                ),
                class_="col-joint-section", style="margin-bottom:8px;"
            )

        # ── TAB 1 · Project ──────────────────────────────────────────────
        tab1 = air.Div(
            air.H2("Project Information"),
            air.Div(
                fg("Project name", "proj_name", data.proj_name, t="text", required=True),
                fg("Location", "proj_loc", data.proj_loc, t="text", required=True),
                fg("Structural engineer", "proj_eng", data.proj_eng, t="text", required=True),
                fg("Date", "proj_date", data.proj_date, t="date", step="", required=True),
                class_="grid-2"
            ),
            tab_footer(next_id="section"),
            id="col-panel-project", class_="col-tab-panel active card"
        )

        # ── TAB 2 · Section ──────────────────────────────────────────────
        depth_display = "display:none;" if data.shape == "circular" else ""
        width_label = "Diameter" if data.shape == "circular" else "Width along x"
        tab2 = air.Div(
            air.H2("Cross-Section"),
            air.Div(
                # Left: inputs
                air.Div(
                    sg("Column shape", "shape",
                       [("Rectangular", "rectangular"), ("Circular", "circular")], data.shape,
                       onchange=(
                           "var c=this.value==='circular';"
                           "document.getElementById('col-depth-grp').style.display=c?'none':'';"
                           "document.getElementById('col-width-lbl').textContent=c?'Diameter':'Width along x';"
                           "if(c){document.getElementById('col_type_sel2').value='tied';}"
                           "drawSectionCanvas();"
                       )),
                    sg("Column type", "column_type",
                       [("Tied", "tied"), ("Spiral", "spiral")], data.column_type,
                       hint="Spiral only for circular columns",
                       onchange="drawSectionCanvas();",
                       id="col_type_sel2"),
                    air.Div(
                        air.Label(width_label, id="col-width-lbl"),
                        air.Div(
                            air.Input(type="number", name="width", value=str(data.width),
                                      required=True, step="any", oninput="drawSectionCanvas();"),
                            air.Span("mm", class_="col-field-unit"),
                            class_="col-field-wrap"
                        ),
                        class_="form-group"
                    ),
                    air.Div(
                        fg("Width along y", "depth", data.depth, unit="mm", required=True,
                           oninput="drawSectionCanvas();"),
                        id="col-depth-grp", style=depth_display
                    ),
                    fg("Floor-to-floor height", "height", data.height, unit="mm", required=True),
                    fg("Clear height", "clear_height", data.clear_height, unit="mm", required=True),
                    fg("Clear cover cc", "cover", data.cover, unit="mm",
                       step="1", min="20", required=True,
                       hint="ACI Table 20.6.1.3 — typically 40 mm for columns",
                       oninput="drawSectionCanvas();"),
                    air.Div(class_="col-section-divider", style="margin-top:16px;"),
                    air.P("Preferred reinforcement", style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
                    air.Div(
                        sg("Main bar size", "pref_main",
                           [(o, o) for o in bar_opts], data.pref_main),
                        sg("Tie / spiral size", "pref_tie",
                           [(o, o) for o in tie_opts], data.pref_tie),
                        class_="grid-2"
                    ),
                ),
                # Right: live canvas
                air.Div(
                    air.Div(
                        air.Canvas(id="col-section-canvas", width="280", height="280"),
                        air.Div(
                            air.Div(
                                air.Div(style="background:#2563eb; width:10px; height:10px; border-radius:50%;", class_="col-legend-dot"),
                                air.Span("Main bars (illustrative)"),
                                class_="col-legend-item"
                            ),
                            air.Div(
                                air.Div(style="background:#db2777; width:10px; height:4px; border-radius:1px;", class_="col-legend-dot"),
                                air.Span("Tie / spiral"),
                                class_="col-legend-item"
                            ),
                            class_="col-canvas-legend"
                        ),
                        air.P("Live preview — bar count shown is illustrative",
                              style="font-size:9px; color:var(--text-muted); font-family:'Space Mono',monospace; margin-top:4px; text-align:center;"),
                        class_="col-canvas-box"
                    ),
                ),
                class_="grid-2"
            ),
            tab_footer(back_id="project", next_id="materials"),
            id="col-panel-section", class_="col-tab-panel card"
        )

        # ── TAB 3 · Materials & Seismic ──────────────────────────────────
        tab3 = air.Div(
            air.H2("Materials \u0026 Seismic Category"),
            air.Div(class_="col-section-divider"),
            air.P("Concrete \u0026 Steel", style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            air.Div(
                fg("Concrete f\u2019c", "fc_prime", data.fc_prime, unit="MPa",
                   hint="ACI \u00a719.2.1.1: 17\u201369 MPa (normal), \u226490 MPa (lightweight)", required=True),
                fg("Main bar fy", "fy", data.fy, unit="MPa",
                   hint="ACI \u00a720.2.2.4: max 690 MPa", required=True),
                fg("Tie / spiral fyt", "fyt", data.fyt, unit="MPa",
                   hint="ACI \u00a722.5.10.2: max 420 MPa for shear", required=True),
                class_="grid-3"
            ),
            air.Div(class_="col-section-divider"),
            air.P("Seismic Classification", style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            air.Div(
                sg("Seismic Design Category (SDC)", "sdc",
                   [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("F", "F")],
                   data.sdc,
                   hint="SDC D/E/F with Special frame triggers joint checks",
                   onchange="updateJointTabVisibility();"),
                sg("Moment frame system", "frame_system",
                   [("Ordinary (OMF)", "ordinary"),
                    ("Intermediate (IMF)", "intermediate"),
                    ("Special (SMF)", "special")],
                   data.frame_system,
                   onchange="updateJointTabVisibility();"),
                class_="grid-2"
            ),
            air.Div(class_="col-section-divider"),
            air.P("Slenderness Parameters", style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            fg("Effective-length factor k", "k_factor", data.k_factor,
               step="0.01", min="0.5", max="2.0", required=True,
               hint="Braced frame k \u22641.0 \u2014 Sway frame k >1.0 (ACI \u00a76.2.5)"),
            tab_footer(back_id="section", next_id="loads"),
            id="col-panel-materials", class_="col-tab-panel card"
        )

        # ── TAB 4 · Loads ────────────────────────────────────────────────
        # M1/M2 curvature hint
        curv_hint = air.Div(
            curvature_svg(double=False),
            curvature_svg(double=True),
            class_="curvature-hint-wrap"
        )

        tab4 = air.Div(
            air.H2("Applied Loads"),
            # Pu — large prominent input
            air.Div(
                air.Label("Factored axial Pu"),
                air.Div(
                    air.Input(type="number", name="pu", value=str(data.pu), step="any",
                              required=True, oninput="drawLoadCanvas();",
                              style="font-size:22px; text-align:center; font-family:'Bebas Neue',sans-serif; letter-spacing:.08em; padding:14px 60px 14px 16px;"),
                    air.Span("kN", class_="col-field-unit",
                             style="font-size:14px; right:14px;"),
                    class_="col-field-wrap"
                ),
                class_="form-group", style="margin-bottom:20px;"
            ),
            # Moments & shears + diagram
            air.Div(
                # Left: inputs
                air.Div(
                    air.H3("Top of Column",
                           style="font-size:16px; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:8px;"),
                    air.Div(
                        fg("Mux", "top_mux", data.top_mux, unit="kN\u00b7m",
                           required=True, oninput="drawLoadCanvas();"),
                        fg("Muy", "top_muy", data.top_muy, unit="kN\u00b7m",
                           required=True, oninput="drawLoadCanvas();"),
                        class_="grid-2"
                    ),
                    air.Div(
                        fg("Vux", "top_vux", data.top_vux, unit="kN",
                           required=True, oninput="drawLoadCanvas();"),
                        fg("Vuy", "top_vuy", data.top_vuy, unit="kN",
                           required=True, oninput="drawLoadCanvas();"),
                        class_="grid-2"
                    ),
                    air.H3("Bottom of Column",
                           style="font-size:16px; margin-top:20px; margin-bottom:12px; border-bottom:1px solid var(--border); padding-bottom:8px;"),
                    air.Div(
                        fg("Mux", "bot_mux", data.bot_mux, unit="kN\u00b7m",
                           required=True, oninput="drawLoadCanvas();"),
                        fg("Muy", "bot_muy", data.bot_muy, unit="kN\u00b7m",
                           required=True, oninput="drawLoadCanvas();"),
                        class_="grid-2"
                    ),
                    air.Div(
                        fg("Vux", "bot_vux", data.bot_vux, unit="kN",
                           required=True, oninput="drawLoadCanvas();"),
                        fg("Vuy", "bot_vuy", data.bot_vuy, unit="kN",
                           required=True, oninput="drawLoadCanvas();"),
                        class_="grid-2"
                    ),
                    class_="section-box"
                ),
                # Right: load diagram canvas
                air.Div(
                    air.Canvas(id="col-load-canvas", width="320", height="380"),
                    air.P("Forces \u2014 updates live",
                          style="font-size:9px; color:var(--text-muted); font-family:'Space Mono',monospace; margin-top:8px; text-align:center;"),
                    air.Div(
                        air.Div(
                            air.Div(style="background:#ef4444; width:10px; height:4px; border-radius:1px;", class_="col-legend-dot"),
                            air.Span("Axial Pu"), class_="col-legend-item"),
                        air.Div(
                            air.Div(style="background:#8b5cf6; width:10px; height:4px; border-radius:1px;", class_="col-legend-dot"),
                            air.Span("Moment M"), class_="col-legend-item"),
                        air.Div(
                            air.Div(style="background:#06b6d4; width:10px; height:4px; border-radius:1px;", class_="col-legend-dot"),
                            air.Span("Shear V"), class_="col-legend-item"),
                        class_="col-canvas-legend", style="margin-top:4px;"
                    ),
                    class_="col-canvas-box"
                ),
                class_="grid-2", style="margin-bottom:16px;"
            ),
            # M1/M2 slenderness
            air.Div(
                air.P("M\u2081/M\u2082 Slenderness Ratios \u2014 ACI \u00a76.2.5",
                      style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:8px;"),
                curv_hint,
                air.P("+1.0 = single curvature (conservative, limit \u2192 22)   \u2014   \u22121.0 = double curvature (relaxed, limit \u2192 40)",
                      style="font-size:10px; color:var(--text-muted); margin-bottom:12px; font-family:'Space Mono',monospace;"),
                air.Div(
                    fg("M\u2081/M\u2082 about x-axis", "m1_m2_x", data.m1_m2_x,
                       step="0.01", min="-1", max="1", required=True,
                       hint="Range: \u22121.0 to +1.0"),
                    fg("M\u2081/M\u2082 about y-axis", "m1_m2_y", data.m1_m2_y,
                       step="0.01", min="-1", max="1", required=True,
                       hint="Range: \u22121.0 to +1.0"),
                    class_="grid-2"
                ),
                style="padding:16px; background:var(--bg-elevated); border-radius:var(--radius); border:1px solid var(--border);"
            ),
            tab_footer(back_id="materials",
                       next_id="joint" if joint_applicable else None),
            id="col-panel-loads", class_="col-tab-panel card"
        )

        # ── TAB 5 · Seismic Joint (inline, no modal) ─────────────────────
        joint_note = air.P(
            "This tab is only required for SDC D/E/F with Special Moment Frame (SMF). "
            "Change the SDC and Frame System in the Materials tab to activate.",
            style="color:var(--text-muted); font-family:'Space Mono',monospace; font-size:11px; padding:16px; background:var(--bg-elevated); border-radius:var(--radius);"
        ) if not joint_applicable else air.Span("")

        tab5 = air.Div(
            air.H2("Seismic Joint Checks"),
            air.P("ACI 318M-25 \u00a718.8 \u2014 Define framing elements at the top joint of this column.",
                  style="color:var(--text-secondary); font-size:13px; margin-bottom:16px;"),
            joint_note,
            air.Div(class_="col-section-divider"),
            air.P("Beams framing along x-direction",
                  style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            air.Div(
                joint_element_block("Left beam (x\u207b)", "top_bx1", "acc-bx1"),
                joint_element_block("Right beam (x\u207a)", "top_bx2", "acc-bx2"),
                class_="grid-2"
            ),
            air.Div(class_="col-section-divider"),
            air.P("Beams framing along y-direction",
                  style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            air.Div(
                joint_element_block("Left beam (y\u207b)", "top_by1", "acc-by1"),
                joint_element_block("Right beam (y\u207a)", "top_by2", "acc-by2"),
                class_="grid-2"
            ),
            air.Div(class_="col-section-divider"),
            air.P("Column above",
                  style="font-family:'Space Mono',monospace; font-size:10px; font-weight:700; color:var(--cyan); letter-spacing:.15em; text-transform:uppercase; margin-bottom:10px;"),
            joint_element_block("Column above", "top_ca", "acc-ca", is_col=True),
            tab_footer(back_id="loads"),
            id="col-panel-joint", class_="col-tab-panel card"
        )

        # ── Tab navigation bar ────────────────────────────────────────────
        joint_btn_style = "" if joint_applicable else "display:none;"
        tab_nav = air.Div(
            air.Button("\u2460 Project", type="button", id="col-tab-project",
                       class_="col-tab-btn active", onclick="colShowTab('project')"),
            air.Button("\u2461 Section", type="button", id="col-tab-section",
                       class_="col-tab-btn", onclick="colShowTab('section')"),
            air.Button("\u2462 Materials", type="button", id="col-tab-materials",
                       class_="col-tab-btn", onclick="colShowTab('materials')"),
            air.Button("\u2463 Loads", type="button", id="col-tab-loads",
                       class_="col-tab-btn", onclick="colShowTab('loads')"),
            air.Button("\u2464 Joint", type="button", id="col-tab-joint",
                       class_="col-tab-btn", onclick="colShowTab('joint')",
                       style=joint_btn_style),
            class_="col-tab-nav"
        )

        return blueprint_layout(
            air.Header(air.A("← Dashboard", href="/", class_="back-link no-print"),
                       air.H1("RC Column Designer"),
                       air.P("in accordance with ACI 318M-25", class_="subtitle"),
                       class_="module-header"),
            air.Main(
                air.Form(
                    air.Input(type="hidden", name="csrf_token", value=csrf_token),
                    tab_nav,
                    tab1, tab2, tab3, tab4, tab5,
                    # Sticky floating Run Analysis button
                    air.Div(
                        air.Button("Run Analysis", type="submit", class_="col-run-btn"),
                        class_="col-run-sticky no-print"
                    ),
                    method="post", action="/column/design"
                )
            ),
            head_extra=[COLUMN_EXTRA_CSS, COLUMN_EXTRA_JS]
        )

    @app.post("/column/design")
    async def column_design(request: air.Request):
        form_data = await request.form()
        try:
            data = ColumnDesignModel(**form_data)
        except Exception as e:
            return AirResponse(content=str(blueprint_layout(
                air.Main(air.Div(air.H2("Validation Failed", style="color: #DC2626;"), air.P(str(e)), class_="card")))),
                               media_type="text/html")

        try:
            frame_enum = FrameSystem(data.frame_system)
            # #9: Use code-table ultimate strengths; fy × 1.25 underestimates Grade 420 fu by ~15 %.
            _FU_LOOKUP = {280: 420.0, 420: 620.0, 520: 690.0, 550: 725.0}
            fu = _FU_LOOKUP.get(round(data.fy), data.fy * 1.5)
            fut = _FU_LOOKUP.get(round(data.fyt), data.fyt * 1.5)
            mat = MaterialProperties(fc_prime=data.fc_prime, fy=data.fy, fu=fu, fyt=data.fyt,
                                     fut=fut, es=200000.0,
                                     ec=base_aci_lib.aci.get_concrete_modulus(data.fc_prime), gamma_c=24.0,
                                     description="")
            col_shape = ColumnShape.CIRCULAR if data.shape == "circular" else ColumnShape.RECTANGULAR
            col_type = ColumnType.SPIRAL if data.column_type == "spiral" else ColumnType.TIED

            # #4: Replicate ACI 318M-25 §26.4.1 guard (mat is constructed directly, not via get_material_properties).
            _fc_warning = (
                f"WARNING: f\u02bcc = {data.fc_prime} MPa exceeds 69 MPa. "
                "ACI 318M-25 \u00a726.4.1 requires special provisions for ultra-high-strength concrete."
            ) if data.fc_prime > 69.0 else None

            # Create engine early so _calc_beam_hinge_capacities is available for #3.
            engine = ACI318M25ColumnDesign()
            engine.reinforcement_limits['min_bar_size'] = data.pref_main

            def get_as(qty, dia):
                return qty * base_aci_lib.aci.get_bar_area(dia)

            bx1_as_top = get_as(data.top_bx1_qty_top, data.top_bx1_dia_top)
            bx1_as_bot = get_as(data.top_bx1_qty_bot, data.top_bx1_dia_bot)
            bx2_as_top = get_as(data.top_bx2_qty_top, data.top_bx2_dia_top)
            bx2_as_bot = get_as(data.top_bx2_qty_bot, data.top_bx2_dia_bot)

            by1_as_top = get_as(data.top_by1_qty_top, data.top_by1_dia_top)
            by1_as_bot = get_as(data.top_by1_qty_bot, data.top_by1_dia_bot)
            by2_as_top = get_as(data.top_by2_qty_top, data.top_by2_dia_top)
            by2_as_bot = get_as(data.top_by2_qty_bot, data.top_by2_dia_bot)

            ca_as = get_as(data.top_ca_qty, data.top_ca_dia)

            # #3: Compute ΣMpr from top-joint beams BEFORE the design call so the engine
            # can use it for the SMF capacity-design shear Ve = (ΣMpr_top + ΣMpr_bot) / lu.
            # Symmetric assumption: same ΣMpr at top and bottom (conservative when bottom joint
            # is not modelled in this tool).
            sum_mpr_top = None
            if data.sdc in ["D", "E", "F"] and data.frame_system == "special":
                _sum_mpr = 0.0
                for _exists, _b, _d, _at, _ab, _fc, _fy in [
                    (data.top_bx1_exists == 'yes', data.top_bx1_b, data.top_bx1_d, bx1_as_top, bx1_as_bot,
                     data.top_bx1_fc, data.top_bx1_fy),
                    (data.top_bx2_exists == 'yes', data.top_bx2_b, data.top_bx2_d, bx2_as_top, bx2_as_bot,
                     data.top_bx2_fc, data.top_bx2_fy),
                    (data.top_by1_exists == 'yes', data.top_by1_b, data.top_by1_d, by1_as_top, by1_as_bot,
                     data.top_by1_fc, data.top_by1_fy),
                    (data.top_by2_exists == 'yes', data.top_by2_b, data.top_by2_d, by2_as_top, by2_as_bot,
                     data.top_by2_fc, data.top_by2_fy),
                ]:
                    if _exists and _b > 0 and _d > 0:
                        _, _, mpr_neg, mpr_pos = engine._calc_beam_hinge_capacities(
                            _b, _d, _at, _ab, _fc, _fy)
                        _sum_mpr += mpr_neg + mpr_pos
                sum_mpr_top = _sum_mpr if _sum_mpr > 0 else None

            # #5: effective_length = k_factor × clear_height.
            # #6: cover comes from the user input (replaces hardcoded 40 mm).
            geom = ColumnGeometry(data.width, data.depth, data.height, data.clear_height, data.cover, col_shape,
                                  col_type, data.k_factor * data.clear_height,
                                  SeismicDesignCategory(data.sdc), frame_enum)
            # #10: Derive LoadCondition from actual moment inputs rather than hardcoding BIAXIAL_BENDING.
            mux_max = max(abs(data.top_mux), abs(data.bot_mux))
            muy_max = max(abs(data.top_muy), abs(data.bot_muy))
            load_cond = (LoadCondition.BIAXIAL_BENDING if mux_max > 0 and muy_max > 0
                         else LoadCondition.UNIAXIAL_BENDING if (mux_max > 0 or muy_max > 0)
                         else LoadCondition.AXIAL_ONLY)
            loads = ColumnLoads(data.pu, mux_max,
                                muy_max, max(abs(data.top_vux), abs(data.bot_vux)),
                                max(abs(data.top_vuy), abs(data.bot_vuy)), load_cond,
                                sum_beam_mpr_top=sum_mpr_top, sum_beam_mpr_bot=sum_mpr_top,
                                m1_m2_x=data.m1_m2_x, m1_m2_y=data.m1_m2_y)

            res = engine.perform_complete_column_design(loads, geom, mat, data.pref_main, data.pref_tie)
            if _fc_warning:
                res.design_notes.insert(0, _fc_warning)

            loads_table = air.Table(
                air.Thead(air.Tr(air.Th("Force"), air.Th("Top Joint"), air.Th("Bot Joint"))),
                air.Tbody(
                    air.Tr(air.Td(air.Strong("Pu (kN)")),
                           air.Td(str(data.pu), colspan="2", style="text-align: center;")),
                    air.Tr(air.Td(air.Strong("Mux (kN·m)")), air.Td(str(data.top_mux)), air.Td(str(data.bot_mux))),
                    air.Tr(air.Td(air.Strong("Muy (kN·m)")), air.Td(str(data.top_muy)), air.Td(str(data.bot_muy))),
                    air.Tr(air.Td(air.Strong("Vux (kN)")), air.Td(str(data.top_vux)), air.Td(str(data.bot_vux))),
                    air.Tr(air.Td(air.Strong("Vuy (kN)")), air.Td(str(data.top_vuy)), air.Td(str(data.bot_vuy)))
                )
            )

            input_content = [
                air.Div(
                    air.H3("Geometry and Materials",
                           style="font-size: 16px; margin-bottom: 8px; border:none; padding:0;"),
                    air.Ul(
                        air.Li(air.Strong("Dimensions"),
                               air.Span(f"Ø{data.width}mm (Lu = {data.clear_height}mm)" if data.shape == "circular" else f"{data.width}mm × {data.depth}mm (Lu = {data.clear_height}mm)",
                                        class_="data-value")),
                        air.Li(air.Strong("Column type"),
                               air.Span(data.column_type.title(), class_="data-value")),
                        air.Li(air.Strong("Seismic"),
                               air.Span(f"SDC {data.sdc}, {frame_enum.value.title()}", class_="data-value")),
                        air.Li(air.Strong("Concrete"), air.Span(f"f'c = {data.fc_prime} MPa", class_="data-value")),
                        air.Li(air.Strong("Steel"),
                               air.Span(f"fy = {data.fy} MPa, fyt = {data.fyt} MPa", class_="data-value")),
                        air.Li(air.Strong("Rebar sizes"),
                               air.Span(f"Main {data.pref_main}, Ties {data.pref_tie}", class_="data-value")),
                    ), class_="section-box"
                ),
                air.Div(
                    air.H3("Loads", style="font-size: 16px; margin-bottom: 8px; border:none; padding:0;"),
                    loads_table, class_="section-box"
                )
            ]

            sc_wb_element = ""
            j_res = None
            if data.sdc in ["D", "E", "F"] and data.frame_system == "special":
                j_res = engine.evaluate_top_joint_seismic(
                    geom, mat, res,
                    JointBeamElement(data.top_bx1_exists == 'yes', data.top_bx1_b, data.top_bx1_d, bx1_as_top,
                                     bx1_as_bot, data.top_bx1_offset, data.top_bx1_fc, data.top_bx1_fy),
                    JointBeamElement(data.top_bx2_exists == 'yes', data.top_bx2_b, data.top_bx2_d, bx2_as_top,
                                     bx2_as_bot, data.top_bx2_offset, data.top_bx2_fc, data.top_bx2_fy),
                    JointBeamElement(data.top_by1_exists == 'yes', data.top_by1_b, data.top_by1_d, by1_as_top,
                                     by1_as_bot, data.top_by1_offset, data.top_by1_fc, data.top_by1_fy),
                    JointBeamElement(data.top_by2_exists == 'yes', data.top_by2_b, data.top_by2_d, by2_as_top,
                                     by2_as_bot, data.top_by2_offset, data.top_by2_fc, data.top_by2_fy),
                    JointColumnElement(data.top_ca_exists == 'yes', data.top_ca_b, data.top_ca_h, ca_as,
                                       data.top_ca_pu), data.pu
                )
                res.design_notes.extend(j_res.notes)
                # Check beam projection beyond column face per ACI 318M-25 §18.8.2.3
                if data.shape == "rectangular":
                    proj_checks = [
                        ("Beam bx1 (x-left)", data.top_bx1_exists, data.top_bx1_b, data.top_bx1_offset, data.depth),
                        ("Beam bx2 (x-right)", data.top_bx2_exists, data.top_bx2_b, data.top_bx2_offset, data.depth),
                        ("Beam by1 (y-left)", data.top_by1_exists, data.top_by1_b, data.top_by1_offset, data.width),
                        ("Beam by2 (y-right)", data.top_by2_exists, data.top_by2_b, data.top_by2_offset, data.width),
                    ]
                    for beam_lbl, exists, beam_bw, offset, c2 in proj_checks:
                        if exists == 'yes':
                            proj = max(0.0, beam_bw / 2.0 + abs(offset) - c2 / 2.0)
                            max_proj = min(c2 / 4.0, 100.0)
                            if proj > max_proj:
                                res.design_notes.append(
                                    f"Violation: {beam_lbl} projects {proj:.0f} mm beyond column face, exceeds {max_proj:.0f} mm limit (ACI 318M-25 §18.8.2.3)"
                                )
                            elif proj > 0:
                                res.design_notes.append(
                                    f"{beam_lbl} projects {proj:.0f} mm beyond column face — within {max_proj:.0f} mm limit (ACI 318M-25 §18.8.2.3)"
                                )
                gamma_val = j_res.x_dir.gamma if j_res.x_dir.exists else j_res.y_dir.gamma
                sc_wb_element = air.Div(
                    air.H4("Seismic Joint Checks", style="color: var(--cyan); margin-bottom: 12px;"),
                    air.Ul(
                        air.Li(air.Strong("Joint confinement factor γ"),
                               air.Span(f"{gamma_val:.1f}", class_="data-value"))
                    ),
                    air.Div(build_scwb_element(j_res.x_dir, "x-direction"),
                            build_scwb_element(j_res.y_dir, "y-direction"), class_="grid-2"),
                    style="margin-top: 16px; padding: 12px; background: var(--bg-elevated); border-radius: 6px; border: 1px dashed var(--border-light);"
                )

                def f_beam(exists, b, d, qt, dt, qb,
                           db): return f"{b}mm x {d}mm (Top: {qt}-{dt}, Bot: {qb}-{db})" if exists == 'yes' else "None"

                def f_col(exists, b, h, q, d_dia,
                          pu): return f"{b}mm x {h}mm ({q}-{d_dia}, Pu = {pu} kN)" if exists == 'yes' else "None"

                input_content.append(
                    air.Div(
                        air.H3("Top Joint Elements",
                               style="font-size: 16px; margin-bottom: 8px; border:none; padding:0;"),
                        air.Ul(
                            air.Li(air.Strong("Beam left (x)"), air.Span(
                                f_beam(data.top_bx1_exists, data.top_bx1_b, data.top_bx1_d, data.top_bx1_qty_top,
                                       data.top_bx1_dia_top, data.top_bx1_qty_bot, data.top_bx1_dia_bot),
                                class_="data-value")),
                            air.Li(air.Strong("Beam right (x)"), air.Span(
                                f_beam(data.top_bx2_exists, data.top_bx2_b, data.top_bx2_d, data.top_bx2_qty_top,
                                       data.top_bx2_dia_top, data.top_bx2_qty_bot, data.top_bx2_dia_bot),
                                class_="data-value")),
                            air.Li(air.Strong("Beam left (y)"), air.Span(
                                f_beam(data.top_by1_exists, data.top_by1_b, data.top_by1_d, data.top_by1_qty_top,
                                       data.top_by1_dia_top, data.top_by1_qty_bot, data.top_by1_dia_bot),
                                class_="data-value")),
                            air.Li(air.Strong("Beam right (y)"), air.Span(
                                f_beam(data.top_by2_exists, data.top_by2_b, data.top_by2_d, data.top_by2_qty_top,
                                       data.top_by2_dia_top, data.top_by2_qty_bot, data.top_by2_dia_bot),
                                class_="data-value")),
                            air.Li(air.Strong("Column above"), air.Span(
                                f_col(data.top_ca_exists, data.top_ca_b, data.top_ca_h, data.top_ca_qty,
                                      data.top_ca_dia, data.top_ca_pu), class_="data-value"))
                        ), class_="section-box"
                    )
                )

            qto = engine.calculate_qto(geom, res, mat)
            rebar_rows = [
                air.Tr(air.Td(air.Strong(r.name)), air.Td(r.size), air.Td(str(r.qty)), air.Td(f"{r.cut_length:.2f}m"),
                       air.Td(r.order), air.Td(f"{r.weight:.1f} kg")) for r in qto.rows]

            n_bars = len(res.reinforcement.longitudinal_bars)
            tie_hinge_str = f"{res.reinforcement.tie_legs_x}x{res.reinforcement.tie_legs_y} legs {res.reinforcement.tie_bars} @ {res.reinforcement.tie_spacing:.0f} mm"
            tie_mid_str = f"{res.reinforcement.tie_legs_x}x{res.reinforcement.tie_legs_y} legs {res.reinforcement.tie_bars} @ {res.reinforcement.tie_spacing_mid:.0f} mm"

            ag = (math.pi / 4.0 * data.width ** 2) if data.shape == "circular" else (data.width * data.depth)
            rho_g = res.reinforcement.longitudinal_area / ag * 100.0
            vux_max = max(abs(data.top_vux), abs(data.bot_vux))
            vuy_max = max(abs(data.top_vuy), abs(data.bot_vuy))
            all_checks_pass = (
                res.capacity.interaction_ratio <= 1.0
                and res.shear_utilization_x <= 1.0
                and res.shear_utilization_y <= 1.0
            )

            def _gauge_row(label, demand_s, cap_s, ratio):
                pct = min(100.0, ratio * 100.0)
                bar_col = "#16A34A" if ratio <= 0.80 else ("#D97706" if ratio <= 1.0 else "#DC2626")
                badge_cls = "pass" if ratio <= 1.0 else "fail"
                sym = "≤" if ratio <= 1.0 else ">"
                return air.Div(
                    air.Div(
                        air.Span(label, style="font-size: 13px; font-weight: 600; color: var(--text-secondary);"),
                        air.Span(f"{demand_s} / {cap_s}", style="font-family: 'Space Mono', monospace; font-size: 11px; color: var(--text-muted);"),
                        style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px;"
                    ),
                    air.Div(
                        air.Div(
                            air.Div(style=f"width: {pct:.1f}%; height: 100%; background: {bar_col}; border-radius: 3px;"),
                            style="flex: 1; height: 8px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden;"
                        ),
                        air.Span(f"{ratio:.2f} {sym} 1.00", class_=f"status-badge {badge_cls}",
                                 style="font-size: 11px; padding: 3px 10px; flex-shrink: 0;"),
                        style="display: flex; align-items: center; gap: 10px;"
                    ),
                    style="padding: 12px 0; border-bottom: 1px solid var(--border);"
                )

            rho_min_lim, rho_max_lim = 1.0, 8.0
            rho_pct = min(100.0, max(0.0, (rho_g - rho_min_lim) / (rho_max_lim - rho_min_lim) * 100.0))
            rho_bar_col = "#16A34A" if rho_min_lim <= rho_g <= rho_max_lim else "#DC2626"

            if data.generate_pdf == "1":
                pdf_bytes = generate_column_report(data, mat, geom, loads, engine, res, n_bars, res.reinforcement.tie_spacing_mid, qto, j_res)
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="column_report.pdf"'}
                )

            notes_elements = [air.Ul(*[air.Li(f"{'⚠️' if any(x in n for x in ['Violation', 'CRITICAL', 'inadequate', 'exceeded']) else 'ℹ️'} {n}") for n in
                                       list(dict.fromkeys(res.design_notes))], class_="notes-list")] if res.design_notes else []

            hidden_inputs = [air.Input(type="hidden", name=k, value=str(v)) for k, v in data.model_dump().items() if k != "generate_pdf"]
            if "csrf_token" in form_data:
                hidden_inputs.append(air.Input(type="hidden", name="csrf_token", value=form_data.get("csrf_token")))

            report_content = air.Main(
                air.Div(
                    air.Form(
                        *hidden_inputs,
                        air.Input(type="hidden", name="generate_pdf", value="1"),
                        air.Button("Print Summary", onclick="window.print()", type="button", style="background-color: var(--accent); color: var(--bg-deep); border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;"),
                        air.Button("Generate Detailed Report", type="submit", style="background-color: var(--accent); color: var(--bg-deep); border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;"),
                        method="post", action="/column/design", style="display: flex; justify-content: flex-end; align-items: center; gap: 8px;"
                    ),
                    style="margin-bottom: 24px;", class_="no-print"
                ),
                air.Div(
                    air.H2("Project Information"),
                    air.Div(
                        air.Div(air.Strong("Project Name: "), air.Span(data.proj_name, class_="data-value")),
                        air.Div(air.Strong("Location: "), air.Span(data.proj_loc, class_="data-value")),
                        air.Div(air.Strong("Structural Engineer: "), air.Span(data.proj_eng, class_="data-value")),
                        air.Div(air.Strong("Date: "), air.Span(data.proj_date, class_="data-value")),
                        style="display: flex; flex-wrap: wrap; gap: 16px; font-size: 16px;"
                    ), class_="card"
                ),
                air.Div(
                    air.H2("Input Parameters"),
                    air.Div(*input_content, class_="grid-3" if len(input_content) == 3 else "grid-2"),
                    class_="card"
                ),
                air.Div(class_="page-break"),
                air.Div(
                    air.H2("Design Results"),
                    air.Div(
                        air.Span("✓" if all_checks_pass else "✕",
                                 style="font-size: 20px; font-weight: 900; line-height: 1;"),
                        air.Span("ALL CHECKS PASS" if all_checks_pass else "ONE OR MORE CHECKS FAIL",
                                 style="font-family: 'Space Mono', monospace; font-size: 12px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;"),
                        style=(
                            "display: flex; align-items: center; gap: 12px; padding: 12px 20px; margin-bottom: 24px; border-radius: 6px; "
                            + ("background: rgba(22,163,74,0.12); border: 1px solid #16A34A; color: #16A34A;"
                               if all_checks_pass else
                               "background: rgba(220,38,38,0.12); border: 1px solid #DC2626; color: #DC2626;")
                        )
                    ),
                    air.Div(
                        air.Div(
                            air.Div("DRAWINGS", class_="col-section-divider"),
                            generate_column_section_css(data.width, data.depth, data.cover, n_bars,
                                                        res.reinforcement.tie_legs_x, res.reinforcement.tie_legs_y,
                                                        data.shape, data.column_type),
                            generate_column_elevation_css(data.height, data.clear_height, max(data.width, data.depth),
                                                          res.reinforcement.tie_spacing, res.reinforcement.tie_spacing_mid,
                                                          data.shape, data.column_type),
                            style="display: flex; flex-direction: column; gap: 16px;"
                        ),
                        air.Div(
                            air.Div("CAPACITY CHECKS", class_="col-section-divider"),
                            _gauge_row(
                                "P-M Interaction",
                                f"Pu={data.pu:.0f} kN",
                                "Unity ≤ 1.00",
                                res.capacity.interaction_ratio
                            ),
                            _gauge_row(
                                "Shear — x direction",
                                f"Vux={vux_max:.1f} kN",
                                f"φVnx={res.capacity.shear_capacity_x:.1f} kN",
                                res.shear_utilization_x
                            ),
                            _gauge_row(
                                "Shear — y direction",
                                f"Vuy={vuy_max:.1f} kN",
                                f"φVny={res.capacity.shear_capacity_y:.1f} kN",
                                res.shear_utilization_y
                            ),
                            air.Div("SECTION CAPACITIES", class_="col-section-divider", style="margin-top: 20px;"),
                            air.Ul(
                                air.Li(air.Strong("φPn (axial)"),
                                       air.Span(f"{res.capacity.axial_capacity:.1f} kN", class_="data-value")),
                                air.Li(air.Strong("φMnx"),
                                       air.Span(f"{res.capacity.moment_capacity_x:.1f} kN·m", class_="data-value")),
                                air.Li(air.Strong("φMny"),
                                       air.Span(f"{res.capacity.moment_capacity_y:.1f} kN·m", class_="data-value")),
                                air.Li(air.Strong("Slenderness amplified"),
                                       air.Span("Yes" if res.capacity.slenderness_effects else "No",
                                                class_="data-value")),
                            ),
                            air.Div("REINFORCEMENT", class_="col-section-divider", style="margin-top: 20px;"),
                            air.Ul(
                                air.Li(air.Strong("Vertical bars"),
                                       air.Span(f"{n_bars}×{data.pref_main}  ({res.reinforcement.longitudinal_area:.0f} mm²)",
                                                class_="data-value", style="color: #2563eb;")),
                                air.Li(
                                    air.Strong("Steel ratio ρg"),
                                    air.Div(
                                        air.Div(
                                            air.Div(style=f"width: {rho_pct:.1f}%; height: 100%; background: {rho_bar_col}; border-radius: 2px;"),
                                            style="flex: 1; height: 6px; background: var(--bg-elevated); border-radius: 2px; overflow: hidden; min-width: 60px;"
                                        ),
                                        air.Span(f"{rho_g:.2f}%", class_="data-value",
                                                 style=f"color: {rho_bar_col}; margin-left: 8px;"),
                                        style="display: flex; align-items: center; gap: 8px; flex: 1; justify-content: flex-end;"
                                    )
                                ),
                                air.Li(air.Strong("Ties (support)"),
                                       air.Span(tie_hinge_str, class_="data-value", style="color: #db2777;")),
                                air.Li(air.Strong("Ties (midheight)"),
                                       air.Span(tie_mid_str, class_="data-value", style="color: #db2777;")),
                            ),
                            sc_wb_element,
                            class_="section-box", style="height: 100%;"
                        ),
                        class_="grid-2"
                    ),
                    *(
                        [air.Div(air.H4("Design Notes", style="margin-top: 20px; color: var(--accent);"), *notes_elements,
                                 style="padding: 16px; background: var(--accent-glow); border-radius: 8px; border: 1px solid var(--border-light); margin-top: 20px;")]
                        if notes_elements else []
                    ),
                    class_="card"
                ),
                air.Div(air.H2("Material Takeoff"), air.Div(
                    air.Div(air.Div("CONCRETE", class_="metric-label"),
                            air.Div(f"{qto.volume:.2f} m³", class_="metric-value"), class_="metric-card concrete"),
                    air.Div(air.Div("FORMWORK", class_="metric-label"),
                            air.Div(f"{qto.formwork:.2f} m²", class_="metric-value"), class_="metric-card formwork"),
                    air.Div(air.Div("REBAR WEIGHT", class_="metric-label"),
                            air.Div(f"{qto.total_weight:.1f} kg", class_="metric-value"), class_="metric-card rebar"),
                    class_="grid-3"),
                        air.Table(air.Thead(
                            air.Tr(air.Th("Location"), air.Th("Size"), air.Th("Qty"), air.Th("Cut Length"),
                                   air.Th("Order"), air.Th("Weight"))), air.Tbody(*rebar_rows)), class_="card"
                        )
            )

            resp = AirResponse(content=str(blueprint_layout(
                air.Header(air.A("← Edit Inputs", href="/column", class_="back-link no-print"),
                           air.H1("RC Column Designer"),
                       air.P("in accordance with ACI 318M-25", class_="subtitle"), class_="module-header"), report_content)),
                               media_type="text/html")
            resp.set_cookie("col_inputs", json.dumps(dict(form_data)), max_age=2592000)
            return resp

        except Exception as e:
            return AirResponse(content=str(blueprint_layout(
                air.Main(air.Div(air.H2("Validation Failed", style="color: #DC2626;"), air.P(str(e)), class_="card")))),
                               media_type="text/html")