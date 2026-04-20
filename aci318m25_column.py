# -*- coding: utf-8 -*-

"""
ACI 318M-25 Column Design Library
Building Code Requirements for Structural Concrete - Column Design
"""

import math
from typing import Dict, Tuple, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
from aci318m25 import ACI318M25, ConcreteStrengthClass, ReinforcementGrade, MaterialProperties


class ColumnType(Enum):
    TIED = "tied"
    SPIRAL = "spiral"
    COMPOSITE = "composite"


class ColumnShape(Enum):
    RECTANGULAR = "rectangular"
    CIRCULAR = "circular"
    L_SHAPED = "l_shaped"
    T_SHAPED = "t_shaped"


class LoadCondition(Enum):
    AXIAL_ONLY = "axial_only"
    UNIAXIAL_BENDING = "uniaxial_bending"
    BIAXIAL_BENDING = "biaxial_bending"


class SeismicDesignCategory(Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class FrameSystem(Enum):
    ORDINARY = "ordinary"
    INTERMEDIATE = "intermediate"
    SPECIAL = "special"


@dataclass
class ColumnGeometry:
    width: float
    depth: float
    height: float
    clear_height: float
    cover: float
    shape: ColumnShape
    column_type: ColumnType
    effective_length: float
    sdc: SeismicDesignCategory = SeismicDesignCategory.A
    frame_system: FrameSystem = FrameSystem.ORDINARY


@dataclass
class ColumnLoads:
    axial_force: float
    moment_x: float
    moment_y: float
    shear_x: float
    shear_y: float
    load_condition: LoadCondition
    sum_beam_mpr_top: Optional[float] = None
    sum_beam_mpr_bot: Optional[float] = None
    sum_beam_mnb_top: Optional[float] = None
    sum_beam_mnb_bot: Optional[float] = None
    # ACI 318M-25 §6.2.5: M1/M2 ratios for per-axis slenderness limit (34 − 12·M1/M2, max 40).
    # M1/M2 positive = single curvature (conservative); negative = double curvature (relaxed limit).
    # Default +1.0 = single curvature → limit = 22 (most conservative, same as legacy behaviour).
    m1_m2_x: float = 1.0
    m1_m2_y: float = 1.0


@dataclass
class ColumnReinforcement:
    longitudinal_bars: List[str]
    longitudinal_area: float
    tie_bars: str
    tie_spacing: float      # confinement zone (hinge) spacing
    tie_legs_x: int
    tie_legs_y: int
    spiral_bar: str
    spiral_pitch: float
    confinement_ratio: float
    tie_spacing_mid: float = 0.0  # mid-height (non-confinement) spacing


@dataclass
class ColumnCapacity:
    axial_capacity: float
    moment_capacity_x: float
    moment_capacity_y: float
    shear_capacity_x: float
    shear_capacity_y: float
    interaction_ratio: float
    slenderness_effects: bool


@dataclass
class ColumnAnalysisResult:
    capacity: ColumnCapacity
    reinforcement: ColumnReinforcement
    utilization_ratio: float
    shear_utilization_x: float
    shear_utilization_y: float
    stability_index: float
    design_notes: List[str]


@dataclass
class JointBeamElement:
    exists: bool
    b: float
    d: float
    as_top: float
    as_bot: float
    offset: float = 0.0    # eccentricity of beam centreline from column centreline (mm)
    fc_prime: float = 0.0  # beam concrete strength (MPa); 0 = fall back to column value
    fy: float = 0.0        # beam rebar yield strength (MPa); 0 = fall back to column value


@dataclass
class JointColumnElement:
    exists: bool
    b: float
    h: float
    as_total: float
    pu: float


@dataclass
class DirectionalJointResult:
    exists: bool
    sum_mnb: float
    sum_mnc: float
    ratio_scwb: float
    vj_u: float
    phi_vj: float
    ratio_vj: float
    gamma: float


@dataclass
class JointAnalysisResult:
    x_dir: DirectionalJointResult
    y_dir: DirectionalJointResult
    notes: List[str]


@dataclass
class QTORow:
    name: str
    size: str
    qty: int
    cut_length: float
    order: str
    weight: float


@dataclass
class QTOResult:
    volume: float
    formwork: float
    total_weight: float
    rows: List[QTORow]


class ACI318M25ColumnDesign:

    def __init__(self):
        self.aci = ACI318M25()
        self.phi_factors = {'compression_tied': 0.65, 'compression_spiral': 0.75, 'flexure': 0.90, 'shear': 0.75}
        self.reinforcement_limits = {'min_ratio': 0.01, 'max_ratio': 0.08, 'min_bars': 4, 'min_bar_size': 'D16'}

    def generate_bar_layout(self, geometry: ColumnGeometry, longitudinal_bars: List[str], assumed_tie: str = 'D10') -> \
    List[Tuple[float, float, float]]:
        if not longitudinal_bars: return []
        N = len(longitudinal_bars)
        db = self.aci.get_bar_diameter(longitudinal_bars[0])
        area = self.aci.get_bar_area(longitudinal_bars[0])
        dt = self.aci.get_bar_diameter(assumed_tie)
        c = geometry.cover
        layout = []

        if geometry.shape == ColumnShape.CIRCULAR:
            Rc = geometry.width / 2.0 - c - dt - db / 2.0
            for i in range(N):
                theta = i * (2 * math.pi / N)
                layout.append((Rc * math.cos(theta), Rc * math.sin(theta), area))
        elif geometry.shape == ColumnShape.RECTANGULAR:
            x_max = geometry.width / 2.0 - c - dt - db / 2.0
            y_max = geometry.depth / 2.0 - c - dt - db / 2.0
            layout.extend([(x_max, y_max, area), (-x_max, y_max, area), (-x_max, -y_max, area), (x_max, -y_max, area)])
            if N > 4:
                rem = N - 4
                ratio = geometry.width / (geometry.width + geometry.depth) if (geometry.width + geometry.depth) > 0 else 0.5
                nx_inter = 2 * int(round(rem * ratio / 2.0))
                ny_inter = rem - nx_inter
                nx_face, ny_face = nx_inter // 2, ny_inter // 2

                if nx_face > 0:
                    spacing_x = (2 * x_max) / (nx_face + 1)
                    for i in range(1, nx_face + 1):
                        x = x_max - i * spacing_x
                        layout.extend([(x, y_max, area), (x, -y_max, area)])
                if ny_face > 0:
                    spacing_y = (2 * y_max) / (ny_face + 1)
                    for i in range(1, ny_face + 1):
                        y = y_max - i * spacing_y
                        layout.extend([(x_max, y, area), (-x_max, y, area)])
        return layout

    def check_minimum_bar_spacing(self, geometry: ColumnGeometry, longitudinal_bars: List[str],
                                   assumed_tie: str = 'D10', d_agg: float = 25.0) -> List[str]:
        """ACI 318M-25 §25.8.1: clear spacing between bars ≥ max(25 mm, db, 4/3·dagg).

        Returns a list of warning strings (empty if all spacings are adequate).
        """
        if not longitudinal_bars:
            return []
        db = self.aci.get_bar_diameter(longitudinal_bars[0])
        dt = self.aci.get_bar_diameter(assumed_tie)
        min_clear = max(25.0, db, (4.0 / 3.0) * d_agg)  # mm
        warnings_list = []

        if geometry.shape == ColumnShape.CIRCULAR:
            N = len(longitudinal_bars)
            Rc = geometry.width / 2.0 - geometry.cover - dt - db / 2.0
            # Arc length between adjacent bar centres divided by db gives clear spacing
            if N >= 2:
                chord = 2.0 * Rc * math.sin(math.pi / N)  # centre-to-centre chord
                clear = chord - db
                if clear < min_clear:
                    warnings_list.append(
                        f"Bar spacing: clear spacing {clear:.1f} mm < "
                        f"required {min_clear:.1f} mm (ACI §25.8.1). "
                        "Increase column diameter or reduce bar count/size.")
        elif geometry.shape == ColumnShape.RECTANGULAR:
            x_max = geometry.width / 2.0 - geometry.cover - dt - db / 2.0
            y_max = geometry.depth / 2.0 - geometry.cover - dt - db / 2.0
            N = len(longitudinal_bars)
            rem = max(0, N - 4)
            ratio = geometry.width / (geometry.width + geometry.depth) if (geometry.width + geometry.depth) > 0 else 0.5
            nx_inter = 2 * int(round(rem * ratio / 2.0))
            ny_inter = rem - nx_inter
            nx_face = nx_inter // 2  # intermediate bars per x-face
            ny_face = ny_inter // 2  # intermediate bars per y-face

            # x-faces: (nx_face + 2) bars over span 2*x_max
            if nx_face + 2 >= 2:
                cc_x = (2 * x_max) / (nx_face + 1)  # centre-to-centre
                clear_x = cc_x - db
                if clear_x < min_clear:
                    warnings_list.append(
                        f"Bar spacing (x-face): clear {clear_x:.1f} mm < "
                        f"required {min_clear:.1f} mm (ACI §25.8.1). "
                        "Increase width, reduce bar count, or use a smaller bar.")

            # y-faces: (ny_face + 2) bars over span 2*y_max
            if ny_face + 2 >= 2:
                cc_y = (2 * y_max) / (ny_face + 1)  # centre-to-centre
                clear_y = cc_y - db
                if clear_y < min_clear:
                    warnings_list.append(
                        f"Bar spacing (y-face): clear {clear_y:.1f} mm < "
                        f"required {min_clear:.1f} mm (ACI §25.8.1). "
                        "Increase depth, reduce bar count, or use a smaller bar.")

        return warnings_list

    def check_seismic_geometric_limits(self, geometry: ColumnGeometry) -> List[str]:
        warnings = []
        if geometry.frame_system == FrameSystem.SPECIAL:
            min_dim = min(geometry.width, geometry.depth)
            max_dim = max(geometry.width, geometry.depth)
            if min_dim < 300.0: warnings.append(
                f"SMF Violation: Minimum column dimension ({min_dim:.0f} mm) must be >= 300 mm.")
            if max_dim > 0 and (min_dim / max_dim) < 0.4: warnings.append(
                f"SMF Violation: Cross-sectional aspect ratio must be >= 0.4.")
            # ACI 318M-25 §18.7.2.1(d): clear height / max cross-sectional dimension ≥ 4
            if max_dim > 0:
                ln_max_ratio = geometry.clear_height / max_dim
                if ln_max_ratio < 4.0:
                    warnings.append(
                        f"SMF Violation: Clear-height-to-max-dimension ratio "
                        f"({ln_max_ratio:.2f}) must be >= 4 per ACI §18.7.2.1(d).")
        return warnings

    def calculate_probable_moment_capacity(self, geometry: ColumnGeometry, material_props: MaterialProperties,
                                           bar_layout: List[Tuple[float, float, float]], axial_load: float,
                                           bending_axis: str = 'x') -> float:
        fc_prime, fy_pr = material_props.fc_prime, 1.25 * material_props.fy
        Es, ecu = 200000.0, 0.003
        P_target = abs(axial_load)

        is_circular = geometry.shape == ColumnShape.CIRCULAR
        if is_circular:
            h = b = geometry.width
            is_x = True
        elif bending_axis == 'x':
            h, b = geometry.depth, geometry.width  # depth in bending direction
            is_x = True
        else:  # 'y'
            h, b = geometry.width, geometry.depth
            is_x = False

        beta1 = 0.85 if fc_prime <= 28 else max(0.65, 0.85 - 0.05 * (fc_prime - 28) / 7.0)
        steel_area = sum(a for _, _, a in bar_layout)
        Ag = geometry.width * geometry.depth if not is_circular else math.pi * (
                    geometry.width / 2) ** 2
        Po = 0.85 * fc_prime * (Ag - steel_area) + fy_pr * steel_area
        if P_target > Po / 1000.0: return 0.001

        curve_Pn, curve_Mn = [], []
        for c in [h * x for x in
                  [10.0, 5.0, 2.0, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.01]]:
            Pn, Mn = 0.0, 0.0
            a = min(beta1 * c, h)
            if a > 0:
                if not is_circular:
                    Cc = (0.85 * fc_prime * a * b) / 1000.0
                    y_c = h / 2.0 - a / 2.0
                else:
                    theta = 2 * math.acos(max(-1.0, min(1.0, 1.0 - 2 * a / h)))
                    area_c = (h / 2.0) ** 2 / 2.0 * (theta - math.sin(theta))
                    Cc = (0.85 * fc_prime * area_c) / 1000.0
                    y_c = (2 * (h / 2.0) * math.sin(theta / 2) ** 3) / (
                                3 * (theta - math.sin(theta))) if theta > 0 else 0
                Pn += Cc;
                Mn += Cc * (y_c / 1000.0)

            for x_bar, y_bar, a_bar in bar_layout:
                d_i = h / 2.0 - y_bar if is_x else h / 2.0 - x_bar
                strain = ecu * (c - d_i) / c
                stress = max(-fy_pr, min(fy_pr, strain * Es))
                if d_i < a: stress -= 0.85 * fc_prime
                Fs = a_bar * stress
                Pn += Fs / 1000.0;
                Mn += (Fs / 1000.0) * (h / 2.0 - d_i) / 1000.0

            curve_Pn.append(Pn);
            curve_Mn.append(Mn)

        for i in range(len(curve_Pn) - 1):
            p1, p2, m1, m2 = curve_Pn[i], curve_Pn[i + 1], curve_Mn[i], curve_Mn[i + 1]
            if min(p1, p2) <= P_target <= max(p1, p2):
                return max(m1, m2) if p1 == p2 else m1 + (m2 - m1) * (P_target - p1) / (p2 - p1)
        return 0.001

    def calculate_nominal_moment_capacity(self, geometry: ColumnGeometry, material_props: MaterialProperties,
                                          bar_layout: List[Tuple[float, float, float]], axial_load: float,
                                          bending_axis: str = 'x') -> float:
        fc_prime, fy = material_props.fc_prime, material_props.fy
        Es, ecu = 200000.0, 0.003
        P_target = abs(axial_load)

        hx, hy = geometry.width, geometry.depth
        is_circular = geometry.shape == ColumnShape.CIRCULAR
        if is_circular:
            h = b = geometry.width
            bending_axis = 'x'
        elif bending_axis == 'x':
            h, b = hy, hx
        else:
            h, b = hx, hy

        beta1 = 0.85 if fc_prime <= 28 else max(0.65, 0.85 - 0.05 * (fc_prime - 28) / 7.0)
        steel_area = sum(a for _, _, a in bar_layout)
        Ag = geometry.width * geometry.depth if not is_circular else math.pi * (geometry.width / 2) ** 2
        Po = 0.85 * fc_prime * (Ag - steel_area) + fy * steel_area
        if P_target > Po / 1000.0: return 0.001

        curve_Pn, curve_Mn = [], []
        for c in [h * x for x in
                  [10.0, 5.0, 2.0, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.01]]:
            Pn, Mn = 0.0, 0.0
            a = min(beta1 * c, h)
            if a > 0:
                if not is_circular:
                    Cc = (0.85 * fc_prime * a * b) / 1000.0
                    y_c = (h / 2.0 - a / 2.0)
                else:
                    theta = 2 * math.acos(max(-1.0, min(1.0, 1.0 - 2 * a / h)))
                    area_c = (h / 2.0) ** 2 / 2.0 * (theta - math.sin(theta))
                    Cc = (0.85 * fc_prime * area_c) / 1000.0
                    y_c = (2 * (h / 2.0) * math.sin(theta / 2) ** 3) / (3 * (theta - math.sin(theta))) if theta > 0 else 0
                Pn += Cc;
                Mn += Cc * (y_c / 1000.0)

            for x_bar, y_bar, a_bar in bar_layout:
                d_i = h / 2.0 - y_bar if bending_axis == 'x' else h / 2.0 - x_bar
                strain = ecu * (c - d_i) / c
                stress = max(-fy, min(fy, strain * Es))
                if d_i < a: stress -= 0.85 * fc_prime
                Fs = a_bar * stress
                Pn += Fs / 1000.0;
                Mn += (Fs / 1000.0) * (h / 2.0 - d_i) / 1000.0

            curve_Pn.append(Pn);
            curve_Mn.append(Mn)

        for i in range(len(curve_Pn) - 1):
            p1, p2, m1, m2 = curve_Pn[i], curve_Pn[i + 1], curve_Mn[i], curve_Mn[i + 1]
            if min(p1, p2) <= P_target <= max(p1, p2):
                return max(m1, m2) if p1 == p2 else m1 + (m2 - m1) * (P_target - p1) / (p2 - p1)
        return 0.001

    def calculate_required_longitudinal_steel(self, loads: ColumnLoads, geometry: ColumnGeometry,
                                              material_props: MaterialProperties) -> float:
        Ag = geometry.width * geometry.depth if geometry.shape == ColumnShape.RECTANGULAR else math.pi * (
                    geometry.width / 2) ** 2
        As_required = self.reinforcement_limits['min_ratio'] * Ag
        if loads.load_condition != LoadCondition.AXIAL_ONLY:
            moment_ratio = abs(loads.moment_x * 1000) / (
                        loads.axial_force * geometry.width / 6) if loads.axial_force > 0 else 2.0
            if moment_ratio > 1.0:
                lever_arm = 0.8 * geometry.depth if geometry.shape == ColumnShape.RECTANGULAR else 0.6 * geometry.width
                As_moment = max(abs(loads.moment_x), abs(loads.moment_y)) * 1e6 / (material_props.fy * lever_arm)
                As_required = max(As_required, As_moment)
        As_max = (0.06 if geometry.frame_system == FrameSystem.SPECIAL else self.reinforcement_limits['max_ratio']) * Ag
        return min(As_required, As_max)

    def design_tie_reinforcement(self, geometry: ColumnGeometry, longitudinal_bars: List[str], loads: ColumnLoads,
                                 material_props: MaterialProperties, pref_tie: str = 'D10') -> Tuple[
        str, float, int, int]:
        if not longitudinal_bars: return pref_tie, 50.0, 2, 2

        long_bar_diameter = self.aci.get_bar_diameter(longitudinal_bars[0])
        tie_size = pref_tie
        tie_diameter = self.aci.get_bar_diameter(tie_size)

        if geometry.shape == ColumnShape.CIRCULAR:
            tie_legs_x = 2
            tie_legs_y = 2
            if geometry.frame_system == FrameSystem.SPECIAL:
                s_max_geom = min(geometry.width / 4.0, 6.0 * long_bar_diameter, 150.0)
                fc_prime, fyt = material_props.fc_prime, material_props.fyt
                bc = geometry.width - 2 * geometry.cover
                Ach = math.pi * (bc / 2.0) ** 2
                Ag = math.pi * (geometry.width / 2.0) ** 2
                
                ash_s_req = max(0.12 * fc_prime / fyt * Ach, 0.3 * (Ag / Ach - 1.0) * fc_prime / fyt * Ach) if geometry.column_type == ColumnType.SPIRAL else max(0.3 * (bc * fc_prime / fyt) * (Ag / Ach - 1.0), 0.09 * bc * fc_prime / fyt)
                
                found = False
                for t_size in ['D10', 'D12', 'D16']:
                    if self.aci.get_bar_area(t_size) < self.aci.get_bar_area(pref_tie): continue
                    A_tie = self.aci.get_bar_area(t_size)
                    s_req = (2 * A_tie) / ash_s_req if ash_s_req > 0 else float('inf')
                    if s_req >= 75.0 or (geometry.column_type == ColumnType.SPIRAL and s_req >= 25.0):
                        tie_size = t_size
                        spacing_confinement = min(s_max_geom, s_req)
                        if geometry.column_type == ColumnType.SPIRAL:
                            spacing_confinement = min(spacing_confinement, 75.0)
                        found = True
                        break
                if not found:
                    tie_size = 'D16'
                    A_tie = self.aci.get_bar_area(tie_size)
                    spacing_confinement = min(s_max_geom, (2 * A_tie) / ash_s_req if ash_s_req > 0 else float('inf'))
            else:
                spacing_confinement = min(16 * long_bar_diameter, 48 * tie_diameter, geometry.width)
                if geometry.column_type == ColumnType.SPIRAL:
                    spacing_confinement = min(spacing_confinement, 75.0)
        else:
            num_bars = len(longitudinal_bars)
            rem = num_bars - 4
            ratio = geometry.width / (geometry.width + geometry.depth) if (geometry.width + geometry.depth) > 0 else 0.5
            nx_inter = 2 * int(round(rem * ratio / 2.0))
            ny_inter = rem - nx_inter

            nx = (nx_inter // 2) + 2
            ny = (ny_inter // 2) + 2

            tie_legs_y = 2
            if nx > 2:
                clear_x = (geometry.width - 2 * geometry.cover - 2 * tie_diameter - long_bar_diameter) / (
                            nx - 1) - long_bar_diameter
                tie_legs_y = nx if clear_x > 150.0 else math.ceil(nx / 2.0) + (1 if nx % 2 == 0 else 0)

            tie_legs_x = 2
            if ny > 2:
                clear_y = (geometry.depth - 2 * geometry.cover - 2 * tie_diameter - long_bar_diameter) / (
                            ny - 1) - long_bar_diameter
                tie_legs_x = ny if clear_y > 150.0 else math.ceil(ny / 2.0) + (1 if ny % 2 == 0 else 0)

            tie_legs_x = min(tie_legs_x, ny)
            tie_legs_y = min(tie_legs_y, nx)

            if geometry.frame_system == FrameSystem.SPECIAL:
                min_col_dim = min(geometry.width, geometry.depth)
                hx_approx = min_col_dim / min(tie_legs_x, tie_legs_y)
                sx = max(100.0, min(100.0 + (350.0 - hx_approx) / 3.0, 150.0))
                s_max_geom = min(min_col_dim / 4.0, 6.0 * long_bar_diameter, sx)

                fc_prime, fyt = material_props.fc_prime, material_props.fyt
                bc_x = geometry.depth - 2 * geometry.cover
                bc_y = geometry.width - 2 * geometry.cover
                Ach = bc_x * bc_y
                Ag = geometry.width * geometry.depth

                ash_s_req_x = max(0.3 * (bc_x * fc_prime / fyt) * (Ag / Ach - 1.0), 0.09 * bc_x * fc_prime / fyt)
                ash_s_req_y = max(0.3 * (bc_y * fc_prime / fyt) * (Ag / Ach - 1.0), 0.09 * bc_y * fc_prime / fyt)

                found = False
                for t_size in ['D10', 'D12', 'D16']:
                    if self.aci.get_bar_area(t_size) < self.aci.get_bar_area(pref_tie): continue
                    A_tie = self.aci.get_bar_area(t_size)

                    for lx in range(tie_legs_x, ny + 1):
                        for ly in range(tie_legs_y, nx + 1):
                            s_req_x = (lx * A_tie) / ash_s_req_x if ash_s_req_x > 0 else float('inf')
                            s_req_y = (ly * A_tie) / ash_s_req_y if ash_s_req_y > 0 else float('inf')

                            s_allowed = min(s_max_geom, s_req_x, s_req_y)
                            if s_allowed >= 75.0:
                                tie_size = t_size
                                tie_legs_x = lx
                                tie_legs_y = ly
                                spacing_confinement = s_allowed
                                found = True
                                break
                        if found: break
                    if found: break

                if not found:
                    tie_size = 'D16'
                    tie_legs_x = ny
                    tie_legs_y = nx
                    A_tie = self.aci.get_bar_area(tie_size)
                    s_req_x = (tie_legs_x * A_tie) / ash_s_req_x if ash_s_req_x > 0 else float('inf')
                    s_req_y = (tie_legs_y * A_tie) / ash_s_req_y if ash_s_req_y > 0 else float('inf')
                    spacing_confinement = min(s_max_geom, s_req_x, s_req_y)
            else:
                spacing_confinement = min(16 * long_bar_diameter, 48 * tie_diameter, min(geometry.width, geometry.depth))

        phi_v = self.phi_factors['shear']
        dx = geometry.width - geometry.cover - tie_diameter - (long_bar_diameter / 2)
        dy = geometry.depth - geometry.cover - tie_diameter - (long_bar_diameter / 2)

        # ACI 318M-25 Table 22.5.5.1: Vc enhanced by axial compression Nu
        Nu_N = max(0.0, loads.axial_force) * 1000.0  # N, compression positive; tension not credited
        if geometry.shape == ColumnShape.CIRCULAR:
            Ag = math.pi * (geometry.width / 2.0)**2
            nu_term = Nu_N / (6.0 * Ag)  # MPa
            Vc_x = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * (0.8 * Ag)
            Vc_y = Vc_x
            Vs_req_x = max(0.0, (abs(loads.shear_x) * 1000 / phi_v) - Vc_x)
            s_shear_x = ((math.pi / 2) * tie_legs_x * self.aci.get_bar_area(tie_size) * material_props.fyt * (0.8 * geometry.width)) / Vs_req_x if Vs_req_x > 0 else float('inf')
            max_s_shear_x = (0.8 * geometry.width) / 4.0 if Vs_req_x > 0.33 * math.sqrt(material_props.fc_prime) * (0.8 * Ag) else (0.8 * geometry.width) / 2.0
            
            Vs_req_y = max(0.0, (abs(loads.shear_y) * 1000 / phi_v) - Vc_y)
            s_shear_y = ((math.pi / 2) * tie_legs_y * self.aci.get_bar_area(tie_size) * material_props.fyt * (0.8 * geometry.width)) / Vs_req_y if Vs_req_y > 0 else float('inf')
            max_s_shear_y = (0.8 * geometry.width) / 4.0 if Vs_req_y > 0.33 * math.sqrt(material_props.fc_prime) * (0.8 * Ag) else (0.8 * geometry.width) / 2.0
        else:
            nu_term = Nu_N / (6.0 * geometry.width * geometry.depth)  # MPa
            Vc_x = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * geometry.depth * dx
            Vs_req_x = max(0.0, (abs(loads.shear_x) * 1000 / phi_v) - Vc_x)
            s_shear_x = (tie_legs_x * self.aci.get_bar_area(tie_size) * material_props.fyt * dx) / Vs_req_x if Vs_req_x > 0 else float('inf')
            max_s_shear_x = dx / 4.0 if Vs_req_x > 0.33 * math.sqrt(material_props.fc_prime) * geometry.depth * dx else dx / 2.0

            Vc_y = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * geometry.width * dy
            Vs_req_y = max(0.0, (abs(loads.shear_y) * 1000 / phi_v) - Vc_y)
            s_shear_y = (tie_legs_y * self.aci.get_bar_area(tie_size) * material_props.fyt * dy) / Vs_req_y if Vs_req_y > 0 else float('inf')
            max_s_shear_y = dy / 4.0 if Vs_req_y > 0.33 * math.sqrt(material_props.fc_prime) * geometry.width * dy else dy / 2.0

        s_final = max(50.0, math.floor(
            min(spacing_confinement, s_shear_x, s_shear_y, max_s_shear_x, max_s_shear_y) / 10.0) * 10.0)
        return tie_size, s_final, tie_legs_x, tie_legs_y

    def calculate_axial_capacity(self, geometry: ColumnGeometry, material_props: MaterialProperties,
                                 steel_area: float) -> float:
        Ag = geometry.width * geometry.depth if geometry.shape == ColumnShape.RECTANGULAR else math.pi * (
                    geometry.width / 2) ** 2
        Po = 0.85 * material_props.fc_prime * (Ag - steel_area) + material_props.fy * steel_area
        return (0.80 * Po if geometry.column_type == ColumnType.TIED else 0.85 * Po) / 1000

    def check_slenderness_effects(self, geometry: ColumnGeometry, loads: ColumnLoads,
                                   material_props: MaterialProperties, As_provided: float) -> Tuple[bool, float, float]:
        # geometry.effective_length is the caller-supplied effective length k·lu (mm).
        # For braced (nonsway) frames k ≤ 1.0; for sway frames k > 1.0.
        # ACI 318M-25 §6.2.5 recommends k = 1.0 for braced unless a more refined analysis is used.
        klu = geometry.effective_length

        if geometry.shape == ColumnShape.RECTANGULAR:
            r_x = geometry.width / (2 * math.sqrt(3))
            r_y = geometry.depth / (2 * math.sqrt(3))
        else:
            r_x = r_y = geometry.width / 4

        kl_r_x = klu / r_x
        kl_r_y = klu / r_y

        # ACI 318M-25 §6.2.5: braced-frame limit = 34 − 12(M1/M2), capped at 40.
        # M1/M2 positive = single curvature; negative = double curvature.
        limit_x = min(40.0, 34.0 - 12.0 * loads.m1_m2_x)
        limit_y = min(40.0, 34.0 - 12.0 * loads.m1_m2_y)

        slender_x = kl_r_x > limit_x
        slender_y = kl_r_y > limit_y

        if not slender_x and not slender_y:
            return False, 1.0, 1.0

        # ACI 318M-25 §6.6.4.5: per-axis magnifier δns = Cm / (1 - Pu / (0.75 * Pc))
        # Cm = 1.0 (conservative, equivalent to uniform moment)
        # Pc = π² * EI / (k * lu)²
        # EI = 0.4 * Ec * Ig / (1 + βdns)  [ACI §6.6.4.4.4b, simpler form]
        # βdns ≈ 0.6 for typical sustained load ratio
        Ec = material_props.ec
        beta_dns = 0.6
        Pu = abs(loads.axial_force)
        Cm = 1.0

        def _compute_mag(Ig_axis: float) -> float:
            EI = 0.4 * Ec * Ig_axis / (1 + beta_dns)
            Pc = (math.pi ** 2 * EI) / klu ** 2 / 1000.0  # kN
            denom = 1.0 - Pu / (0.75 * Pc) if Pc > 0 else 0.0
            if denom <= 0:
                return 2.0  # section is unstable; cap at 2.0
            return max(1.0, Cm / denom)

        # Ig about the axis that resists bending in that direction:
        #   Bending about x-axis (moment causes curvature in x-z plane) uses width as the bending dimension
        #   → Ig,x = depth × width³ / 12  (second moment about the centroidal x-axis)
        #   Bending about y-axis (moment causes curvature in y-z plane) uses depth as the bending dimension
        #   → Ig,y = width × depth³ / 12  (second moment about the centroidal y-axis)
        if geometry.shape == ColumnShape.RECTANGULAR:
            Ig_x = geometry.depth * geometry.width ** 3 / 12.0   # about x-axis (width bends)
            Ig_y = geometry.width * geometry.depth ** 3 / 12.0   # about y-axis (depth bends)
        else:
            Ig_x = Ig_y = math.pi * (geometry.width / 2) ** 4 / 4.0

        mag_x = _compute_mag(Ig_x) if slender_x else 1.0
        mag_y = _compute_mag(Ig_y) if slender_y else 1.0

        return True, mag_x, mag_y

    def calculate_pm_interaction(self, geometry: ColumnGeometry, material_props: MaterialProperties,
                                 bar_layout: List[Tuple[float, float, float]], loads: ColumnLoads) -> float:
        fc_prime, fy = material_props.fc_prime, material_props.fy
        Es, ecu = 200000.0, 0.003
        Pu, Mux, Muy = abs(loads.axial_force), abs(loads.moment_x), abs(loads.moment_y)

        hx, hy = geometry.depth, geometry.width
        beta1 = 0.85 if fc_prime <= 28 else max(0.65, 0.85 - 0.05 * (fc_prime - 28) / 7.0)
        phi_c = self.phi_factors['compression_tied'] if geometry.column_type == ColumnType.TIED else self.phi_factors['compression_spiral']
        phi_f = self.phi_factors['flexure']

        Pn_max = self.calculate_axial_capacity(geometry, material_props, sum(a for _, _, a in bar_layout))
        axial_ratio = Pu / (phi_c * Pn_max) if Pn_max > 0 else float('inf')
        if axial_ratio >= 1.0 or (Mux < 0.01 and Muy < 0.01): return axial_ratio

        def compute_capacity_at_axis(h, b, is_x_axis):
            is_circular = geometry.shape == ColumnShape.CIRCULAR
            curve_Pn, curve_phi_Mn = [], []
            for c in [h * x for x in
                      [10.0, 5.0, 2.0, 1.5, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.01]]:
                Pn, Mn = 0.0, 0.0
                a = min(beta1 * c, h)
                if a > 0:
                    if not is_circular:
                        Cc = (0.85 * fc_prime * a * b) / 1000.0
                        y_c = (h / 2.0 - a / 2.0)
                    else:
                        theta = 2 * math.acos(max(-1.0, min(1.0, 1.0 - 2 * a / h)))
                        area_c = (h / 2.0) ** 2 / 2.0 * (theta - math.sin(theta))
                        Cc = (0.85 * fc_prime * area_c) / 1000.0
                        y_c = (2 * (h / 2.0) * math.sin(theta / 2) ** 3) / (3 * (theta - math.sin(theta))) if theta > 0 else 0
                    Pn += Cc;
                    Mn += Cc * (y_c / 1000.0)

                max_di = 0.0
                for x_bar, y_bar, a_bar in bar_layout:
                    d_i = h / 2.0 - y_bar if is_x_axis else h / 2.0 - x_bar
                    strain = ecu * (c - d_i) / c
                    stress = max(-fy, min(fy, strain * Es))
                    if d_i < a: stress -= 0.85 * fc_prime
                    Fs = a_bar * stress
                    Pn += Fs / 1000.0;
                    Mn += (Fs / 1000.0) * (h / 2.0 - d_i) / 1000.0
                    if d_i > max_di: max_di = d_i
                # Signed net tensile strain at the extreme tension bar.
                # Positive = tension (bar beyond neutral axis), negative = compression.
                et = (max_di - c) * ecu / c

                ey = fy / Es
                phi = phi_c if et <= ey else (
                    phi_f if et >= 0.005 else phi_c + (phi_f - phi_c) * (et - ey) / (0.005 - ey))
                curve_Pn.append(min(Pn, Pn_max) * phi);
                curve_phi_Mn.append(Mn * phi)
            return curve_Pn, curve_phi_Mn

        Pn_curve_x, phi_Mnx_curve = compute_capacity_at_axis(hx, hy, True)
        Pn_curve_y, phi_Mny_curve = compute_capacity_at_axis(hy, hx, False)

        def get_moment_at_Pu(P_target, P_curve, M_curve):
            for i in range(len(P_curve) - 1):
                if min(P_curve[i], P_curve[i + 1]) <= P_target <= max(P_curve[i], P_curve[i + 1]):
                    return max(M_curve[i], M_curve[i + 1]) if P_curve[i] == P_curve[i + 1] else M_curve[i] + (
                                M_curve[i + 1] - M_curve[i]) * (P_target - P_curve[i]) / (P_curve[i + 1] - P_curve[i])
            return 0.001

        phi_Mnx, phi_Mny = get_moment_at_Pu(Pu, Pn_curve_x, phi_Mnx_curve), get_moment_at_Pu(Pu, Pn_curve_y,
                                                                                             phi_Mny_curve)
        alpha = 1.15 if geometry.shape == ColumnShape.RECTANGULAR else 1.5
        ratio_x, ratio_y = (Mux / phi_Mnx) if phi_Mnx > 0 else 0, (Muy / phi_Mny) if phi_Mny > 0 else 0
        return max((ratio_x ** alpha + ratio_y ** alpha) ** (1.0 / alpha), axial_ratio)

    def calculate_shear_capacity(self, geometry: ColumnGeometry, material_props: MaterialProperties,
                                 transverse_bar: str, spacing: float, legs_x: int, legs_y: int,
                                 longitudinal_bars: List[str], vc_zero: bool = False,
                                 Nu: float = 0.0) -> Tuple[float, float]:
        """Nu = factored axial compression force (N, positive = compression)."""
        if not transverse_bar or spacing <= 0: return 0.0, 0.0
        tie_diameter = self.aci.get_bar_diameter(transverse_bar)
        long_bar_diameter = self.aci.get_bar_diameter(longitudinal_bars[0]) if longitudinal_bars else 20.0
        dx = geometry.width - geometry.cover - tie_diameter - (long_bar_diameter / 2)
        dy = geometry.depth - geometry.cover - tie_diameter - (long_bar_diameter / 2)

        if geometry.shape == ColumnShape.CIRCULAR:
            Ag = math.pi * (geometry.width / 2.0)**2
            if vc_zero:
                Vc_x = 0.0
                Vc_y = 0.0
            else:
                # ACI 318M-25 Table 22.5.5.1: Vc enhanced by axial compression
                nu_term = max(0.0, Nu) / (6.0 * Ag)  # MPa; tension (Nu<0) not credited
                Vc_x = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * (0.8 * Ag)
                Vc_y = Vc_x
            Vs_x = min(((math.pi / 2) * legs_x * self.aci.get_bar_area(transverse_bar) * material_props.fyt * (0.8 * geometry.width)) / spacing,
                       0.66 * math.sqrt(material_props.fc_prime) * (0.8 * Ag))
            Vs_y = min(((math.pi / 2) * legs_y * self.aci.get_bar_area(transverse_bar) * material_props.fyt * (0.8 * geometry.width)) / spacing,
                       0.66 * math.sqrt(material_props.fc_prime) * (0.8 * Ag))
        else:
            if vc_zero:
                Vc_x = 0.0
                Vc_y = 0.0
            else:
                # ACI 318M-25 Table 22.5.5.1: Vc enhanced by axial compression
                Ag_rect = geometry.width * geometry.depth
                nu_term = max(0.0, Nu) / (6.0 * Ag_rect)  # MPa; tension (Nu<0) not credited
                Vc_x = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * geometry.depth * dx
                Vc_y = (0.17 * math.sqrt(material_props.fc_prime) + nu_term) * geometry.width * dy
            Vs_x = min((legs_x * self.aci.get_bar_area(transverse_bar) * material_props.fyt * dx) / spacing,
                       0.66 * math.sqrt(material_props.fc_prime) * geometry.depth * dx)
            Vs_y = min((legs_y * self.aci.get_bar_area(transverse_bar) * material_props.fyt * dy) / spacing,
                       0.66 * math.sqrt(material_props.fc_prime) * geometry.width * dy)

        return self.phi_factors['shear'] * (Vc_x + Vs_x) / 1000.0, self.phi_factors['shear'] * (Vc_y + Vs_y) / 1000.0

    def perform_complete_column_design(self, loads: ColumnLoads, geometry: ColumnGeometry,
                                       material_props: MaterialProperties, pref_main: str,
                                       pref_tie: str) -> ColumnAnalysisResult:
        base_design_notes = self.check_seismic_geometric_limits(geometry)
        Ag = geometry.width * geometry.depth if geometry.shape == ColumnShape.RECTANGULAR else math.pi * (
                    geometry.width / 2) ** 2
        min_rho = self.reinforcement_limits['min_ratio']
        max_rho = 0.06 if geometry.frame_system == FrameSystem.SPECIAL else self.reinforcement_limits['max_ratio']

        As_guess = self.calculate_required_longitudinal_steel(loads, geometry, material_props)
        start_rho = max(min_rho, math.floor(max(min_rho, min(As_guess / Ag, max_rho)) * 200) / 200.0)

        current_rho = start_rho
        best_result = None

        while current_rho <= max_rho + 1e-5:
            current_notes = list(base_design_notes)
            area_bar = self.aci.get_bar_area(pref_main)
            num_bars = max(4 if geometry.shape == ColumnShape.RECTANGULAR else 6,
                           math.ceil((current_rho * Ag) / area_bar))
            if geometry.shape == ColumnShape.RECTANGULAR and num_bars % 2 != 0: num_bars += 1
            longitudinal_bars = [pref_main] * num_bars

            As_provided = sum(self.aci.get_bar_area(bar) for bar in longitudinal_bars)
            bar_layout = self.generate_bar_layout(geometry, longitudinal_bars, assumed_tie=pref_tie)

            # ACI 318M-25 §25.8.1: verify minimum clear bar spacing.
            spacing_warnings = self.check_minimum_bar_spacing(geometry, longitudinal_bars, assumed_tie=pref_tie)
            current_notes.extend(spacing_warnings)

            tie_size, tie_spacing, tie_legs_x, tie_legs_y = self.design_tie_reinforcement(geometry, longitudinal_bars,
                                                                                          loads, material_props,
                                                                                          pref_tie)
            Vu_Nu = max(0.0, loads.axial_force) * 1000.0  # N, compression positive
            phi_Vnx, phi_Vny = self.calculate_shear_capacity(geometry, material_props, tie_size, tie_spacing,
                                                             tie_legs_x, tie_legs_y, longitudinal_bars,
                                                             Nu=Vu_Nu)

            if geometry.frame_system == FrameSystem.SPECIAL and tie_spacing < 75.0:
                current_notes.append(
                    f"CRITICAL: Tight tie spacing ({tie_spacing:.0f} mm) needed for confinement. Consider larger column or more main bars to provide tie anchors.")

            Ve_x, Ve_y = abs(loads.shear_x), abs(loads.shear_y)
            if geometry.frame_system == FrameSystem.SPECIAL:
                lu_m = getattr(geometry, 'clear_height', geometry.height - 600) / 1000.0

                # Issue #6: Report confinement zone length and middle-zone spacing (ACI §18.7.5.1 & §18.7.5.6)
                long_bar_d_smf = self.aci.get_bar_diameter(pref_main)
                lo_mm = max(max(geometry.width, geometry.depth),
                            geometry.clear_height / 6.0,
                            450.0)
                s_middle_smf = min(6.0 * long_bar_d_smf, 150.0)  # ACI §18.7.5.6
                current_notes.append(
                    f"SMF Confinement zone: lo = {lo_mm:.0f} mm at each end (ACI §18.7.5.1). "
                    f"Confinement s = {tie_spacing:.0f} mm within lo; "
                    f"middle zone s ≤ {s_middle_smf:.0f} mm (ACI §18.7.5.6).")

                # Issue #15: ACI 318M-25 §18.7.5.3 — hx ≤ 350 mm (c/c of tie legs on each face).
                # hx along the depth face = (depth - 2·cover) / (tie_legs_x - 1) legs in that dir.
                # hx along the width face = (width - 2·cover) / (tie_legs_y - 1) legs in that dir.
                if geometry.shape != ColumnShape.CIRCULAR:
                    hx_depth = (geometry.depth - 2.0 * geometry.cover) / max(tie_legs_x - 1, 1)
                    hx_width = (geometry.width - 2.0 * geometry.cover) / max(tie_legs_y - 1, 1)
                    hx_max = max(hx_depth, hx_width)
                    if hx_max > 350.0:
                        current_notes.append(
                            f"SMF Violation: Maximum tie-leg spacing hx = {hx_max:.0f} mm "
                            f"exceeds 350 mm limit (ACI §18.7.5.3). "
                            f"Add crosstie legs to reduce hx.")

                # Issue #10: Evaluate Mpr per bending axis for correct per-axis Ve
                # ACI 318M-25 §18.7.6.1: Ve = (Mpr_top + Mpr_bot) / ln.
                # Evaluate at design Pu and zero Pu to find the governing load level.
                Mpr_x_des  = self.calculate_probable_moment_capacity(geometry, material_props, bar_layout, loads.axial_force, 'x')
                Mpr_x_zero = self.calculate_probable_moment_capacity(geometry, material_props, bar_layout, 0.0, 'x')
                Mpr_c_x = max(Mpr_x_des, Mpr_x_zero)
                Ve_req_x = (2.0 * Mpr_c_x) / lu_m if lu_m > 0 else Ve_x

                Mpr_y_des  = self.calculate_probable_moment_capacity(geometry, material_props, bar_layout, loads.axial_force, 'y')
                Mpr_y_zero = self.calculate_probable_moment_capacity(geometry, material_props, bar_layout, 0.0, 'y')
                Mpr_c_y = max(Mpr_y_des, Mpr_y_zero)
                Ve_req_y = (2.0 * Mpr_c_y) / lu_m if lu_m > 0 else Ve_y

                current_notes.append(
                    f"SMF Capacity Design: Ve,x = {Ve_req_x:.1f} kN (Mpr,x = {Mpr_c_x:.1f} kN·m), "
                    f"Ve,y = {Ve_req_y:.1f} kN (Mpr,y = {Mpr_c_y:.1f} kN·m).")
                Ve_x = max(Ve_x, Ve_req_x)
                Ve_y = max(Ve_y, Ve_req_y)

                # Issue #9: Correct Vc = 0 trigger per ACI §18.7.6.2.1(a):
                # Vc = 0 when the seismic-induced shear Ve >= 0.5 × total shear demand Vu AND low axial load.
                vc_zero = ((Ve_req_x >= 0.5 * Ve_x or Ve_req_y >= 0.5 * Ve_y) and
                           loads.axial_force * 1000 < 0.05 * material_props.fc_prime * Ag)
                if vc_zero:
                    current_notes.append(
                        "SMF Detailing: Vc taken as 0 per ACI §18.7.6.2.1(a) (seismic shear ≥ 0.5Vu and low axial load).")
                    phi_Vnx, phi_Vny = self.calculate_shear_capacity(
                        geometry, material_props, tie_size, tie_spacing,
                        tie_legs_x, tie_legs_y, longitudinal_bars, vc_zero=True,
                        Nu=Vu_Nu)

            if phi_Vnx <= 0:
                shear_util_x = float('inf')  # zero shear capacity is a design error, not 0 % utilisation
                current_notes.append("ERROR: phi_Vn = 0 in x-direction; verify shear reinforcement.")
            else:
                shear_util_x = Ve_x / phi_Vnx
            if phi_Vny <= 0:
                shear_util_y = float('inf')
                current_notes.append("ERROR: phi_Vn = 0 in y-direction; verify shear reinforcement.")
            else:
                shear_util_y = Ve_y / phi_Vny
            slenderness_req, mag_x, mag_y = self.check_slenderness_effects(geometry, loads, material_props, As_provided)
            interaction_ratio = self.calculate_pm_interaction(geometry, material_props, bar_layout,
                                                              ColumnLoads(loads.axial_force,
                                                                          loads.moment_x * mag_x,
                                                                          loads.moment_y * mag_y, loads.shear_x,
                                                                          loads.shear_y,
                                                                          loads.load_condition) if slenderness_req else loads)

            if slenderness_req: current_notes.append(f"Slenderness considered (δns,x = {mag_x:.2f}, δns,y = {mag_y:.2f})")
            if interaction_ratio > 1.0: current_notes.append(
                "Section inadequate in P-M interaction - increasing steel...")
            if shear_util_x > 1.0 or shear_util_y > 1.0: current_notes.append(
                "Section inadequate in shear - increasing tie size/legs...")

            gov_util = max(interaction_ratio, shear_util_x, shear_util_y)

            # Mid-height (non-confinement) tie spacing per ACI §18.7.5.6 / §25.7.2.
            # For SMF: min(6·db_main, 150 mm). For non-SMF: same as confinement spacing.
            _db_main = self.aci.get_bar_diameter(pref_main)
            if geometry.frame_system == FrameSystem.SPECIAL:
                s_mid = max(50.0, math.floor(min(6.0 * _db_main, 150.0) / 10.0) * 10.0)
            else:
                s_mid = tie_spacing
            reinforcement = ColumnReinforcement(longitudinal_bars, As_provided, tie_size, tie_spacing, tie_legs_x,
                                                tie_legs_y, "", 0.0, 0.0, tie_spacing_mid=s_mid)
            phi_c_val = self.phi_factors['compression_spiral'] if geometry.column_type == ColumnType.SPIRAL else self.phi_factors['compression_tied']
            phi_mnx = phi_c_val * self.calculate_nominal_moment_capacity(geometry, material_props, bar_layout, loads.axial_force, 'x')
            phi_mny = phi_c_val * self.calculate_nominal_moment_capacity(geometry, material_props, bar_layout, loads.axial_force, 'y')
            capacity = ColumnCapacity(phi_c_val * self.calculate_axial_capacity(geometry, material_props, As_provided),
                                      phi_mnx, phi_mny,
                                      phi_Vnx, phi_Vny, interaction_ratio, slenderness_req)
            last_result = ColumnAnalysisResult(capacity, reinforcement, gov_util, shear_util_x, shear_util_y, 0.0,
                                               current_notes)

            if gov_util <= 1.0:
                best_result = last_result
                break
            current_rho += 0.005

        if best_result is not None: return best_result
        last_result.design_notes.append(
            "CRITICAL: Section inadequate even with maximum reinforcement limit. Increase column dimensions.")
        return last_result

    def _calc_beam_hinge_capacities(self, b, d, as_top, as_bot, fc, fy):
        if b <= 0 or d <= 0: return 0, 0, 0, 0
        fy_pr = 1.25 * fy
        mn_neg = as_top * fy * (d - (as_top * fy) / (0.85 * fc * b) / 2.0) / 1e6 if as_top > 0 else 0
        mn_pos = as_bot * fy * (d - (as_bot * fy) / (0.85 * fc * b) / 2.0) / 1e6 if as_bot > 0 else 0
        mpr_neg = as_top * fy_pr * (d - (as_top * fy_pr) / (0.85 * fc * b) / 2.0) / 1e6 if as_top > 0 else 0
        mpr_pos = as_bot * fy_pr * (d - (as_bot * fy_pr) / (0.85 * fc * b) / 2.0) / 1e6 if as_bot > 0 else 0
        return mn_neg, mn_pos, mpr_neg, mpr_pos

    def evaluate_top_joint_seismic(self, col_geom: ColumnGeometry, mat_props: MaterialProperties,
                                   col_res: ColumnAnalysisResult,
                                   bx1: JointBeamElement, bx2: JointBeamElement, by1: JointBeamElement,
                                   by2: JointBeamElement,
                                   ca: JointColumnElement, pu: float) -> JointAnalysisResult:
        notes = []

        # Unified gamma per ACI 318M-25 Table 18.8.3.1 — single value for both directions.
        # Confinement: beam width >= 3/4 of the column face it frames into.
        # bx1/bx2 frame into the y-face (col_geom.depth); by1/by2 frame into the x-face (col_geom.width).
        c_bx1 = bx1.exists and bx1.b >= 0.75 * col_geom.depth
        c_bx2 = bx2.exists and bx2.b >= 0.75 * col_geom.depth
        c_by1 = by1.exists and by1.b >= 0.75 * col_geom.width
        c_by2 = by2.exists and by2.b >= 0.75 * col_geom.width
        confined_count = sum([c_bx1, c_bx2, c_by1, c_by2])
        gamma = (1.7 if confined_count == 4 else
                 1.2 if (confined_count >= 3 or (c_bx1 and c_bx2) or (c_by1 and c_by2)) else
                 1.0)

        def evaluate_direction(b1: JointBeamElement, b2: JointBeamElement, col_b: float, col_h: float,
                               bending_axis: str):
            # Issue #8: use each beam's own material properties; fall back to column values when not provided.
            b1_fc = b1.fc_prime if (b1.exists and b1.fc_prime > 0) else mat_props.fc_prime
            b1_fy = b1.fy     if (b1.exists and b1.fy > 0)     else mat_props.fy
            b2_fc = b2.fc_prime if (b2.exists and b2.fc_prime > 0) else mat_props.fc_prime
            b2_fy = b2.fy     if (b2.exists and b2.fy > 0)     else mat_props.fy
            mnb_neg1, mnb_pos1, mpr_neg1, mpr_pos1 = self._calc_beam_hinge_capacities(
                b1.b, b1.d, b1.as_top, b1.as_bot, b1_fc, b1_fy) if b1.exists else (0, 0, 0, 0)
            mnb_neg2, mnb_pos2, mpr_neg2, mpr_pos2 = self._calc_beam_hinge_capacities(
                b2.b, b2.d, b2.as_top, b2.as_bot, b2_fc, b2_fy) if b2.exists else (0, 0, 0, 0)
            sum_mnb = max(mnb_pos1 + mnb_neg2, mnb_neg1 + mnb_pos2)

            if sum_mnb == 0: return DirectionalJointResult(False, 0, 0, 0, 0, 0, 0, gamma)

            layout_below = self.generate_bar_layout(col_geom, col_res.reinforcement.longitudinal_bars,
                                                    col_res.reinforcement.tie_bars)
            mnc_below = self.calculate_nominal_moment_capacity(col_geom, mat_props, layout_below, pu, bending_axis)

            mnc_above = 0.0
            if ca.exists:
                ca_geom = ColumnGeometry(ca.b, ca.h, 3000, 3000, 40, ColumnShape.RECTANGULAR, ColumnType.TIED, 3000)
                a_bar = ca.as_total / 4.0
                cx, cy = max(10.0, ca.b / 2 - 50.0), max(10.0, ca.h / 2 - 50.0)
                ca_layout = [(cx, cy, a_bar), (-cx, cy, a_bar), (-cx, -cy, a_bar), (cx, -cy, a_bar)]
                mnc_above = self.calculate_nominal_moment_capacity(ca_geom, mat_props, ca_layout, ca.pu, bending_axis)

            sum_mnc = mnc_below + mnc_above
            ratio_scwb = sum_mnc / sum_mnb
            if ratio_scwb < 1.2: notes.append(
                f"SMF Violation: SC/WB ratio in {bending_axis.upper()}-Direction is {ratio_scwb:.2f}. Must be >= 1.2.")

            # Effective joint width per ACI 318M-25 §18.8.2.3, accounting for beam eccentricity.
            # bj = min(col_b - 2|e|, bb + col_h) for each beam; take the most conservative.
            bj = col_b
            for beam in [b1, b2]:
                if beam.exists:
                    e = abs(beam.offset)
                    bj = min(bj, col_b - 2.0 * e, beam.b + col_h)
            bj = max(0.0, bj)

            # ACI 318M-25 Table 18.8.3.1: φVj = 0.85 × λ × γ × √f'c × Aj
            phi_vj = 0.85 * mat_props.lambda_factor * gamma * math.sqrt(mat_props.fc_prime) * (bj * col_h) / 1000.0

            t1 = 1.25 * mat_props.fy * b1.as_top / 1000.0 if b1.exists else 0
            c2_sw = 1.25 * mat_props.fy * b2.as_bot / 1000.0 if b2.exists else 0
            vcol1 = (mpr_neg1 + mpr_pos2) / (col_geom.height / 1000.0) if col_geom.height > 0 else 0
            vj_sway1 = t1 + c2_sw - vcol1

            t2 = 1.25 * mat_props.fy * b2.as_top / 1000.0 if b2.exists else 0
            c1_sw = 1.25 * mat_props.fy * b1.as_bot / 1000.0 if b1.exists else 0
            vcol2 = (mpr_neg2 + mpr_pos1) / (col_geom.height / 1000.0) if col_geom.height > 0 else 0
            vj_sway2 = t2 + c1_sw - vcol2

            vj_u = max(abs(vj_sway1), abs(vj_sway2))
            ratio_vj = vj_u / phi_vj if phi_vj > 0 else 9.99

            return DirectionalJointResult(True, sum_mnb, sum_mnc, ratio_scwb, vj_u, phi_vj, ratio_vj, gamma)

        x_res = evaluate_direction(bx1, bx2, col_geom.depth, col_geom.width, 'y')
        y_res = evaluate_direction(by1, by2, col_geom.width, col_geom.depth, 'x')

        return JointAnalysisResult(x_res, y_res, notes)

    def calculate_qto(self, geom: ColumnGeometry, res: ColumnAnalysisResult,
                      mat: 'MaterialProperties | None' = None) -> QTOResult:
        b_m, h_m, L_m = geom.width / 1000.0, geom.depth / 1000.0, geom.height / 1000.0
        vol_concrete = b_m * h_m * L_m
        area_formwork = (2 * (b_m + h_m) + 0.2) * L_m
        rows = []
        total_kg = 0.0

        def get_db(bar_str):
            try:
                return float(bar_str.split(" ")[1].replace('D', '') if "-leg" in bar_str else bar_str.replace('D', ''))
            except:
                return 16.0

        def get_best_commercial_order(req_len, qty, db_mm):
            # ACI 318M-25 §25.3.2: 135° hook extension = max(6db, 75 mm).
            hook_ext_m = max(6.0 * db_mm, 75.0) / 1000.0  # metres
            stocks, splice_m = [6.0, 7.5, 9.0, 10.5, 12.0], 40 * db_mm / 1000.0
            if req_len > 12.0:
                eff_12 = 12.0 - splice_m
                num_12 = int(req_len // eff_12)
                rem = req_len - num_12 * eff_12
                if rem > 0: rem += splice_m
                best_waste, best_S, best_count = float('inf'), 12.0, 0
                if rem > 0:
                    for S in stocks:
                        if S >= rem:
                            pieces = int(S // rem)
                            if pieces > 0:
                                count = math.ceil(qty / pieces)
                                waste = count * S - (qty * rem)
                                if waste < best_waste: best_waste, best_S, best_count = waste, S, count
                order_parts = []
                if num_12 * qty > 0: order_parts.append(f"{num_12 * qty} x 12.0m")
                if rem > 0 and best_count > 0: order_parts.append(f"{best_count} x {best_S}m")
                return " + ".join(order_parts), ((num_12 * qty) * 12.0 + (best_count * best_S if rem > 0 else 0))
            else:
                best_waste, best_S, best_count = float('inf'), 12.0, 0
                for S in stocks:
                    if S >= req_len:
                        pieces = int(S // req_len)
                        if pieces > 0:
                            count = math.ceil(qty / pieces)
                            waste = count * S - (qty * req_len)
                            if waste < best_waste: best_waste, best_S, best_count = waste, S, count
                return f"{best_count} x {best_S}m", best_count * best_S

        if res.reinforcement.longitudinal_bars:
            db_main = get_db(res.reinforcement.longitudinal_bars[0])
            num_main = len(res.reinforcement.longitudinal_bars)

            num_spliced = math.ceil(num_main / 2.0)
            num_unspliced = num_main - num_spliced

            if num_spliced > 0:
                # ACI 318M-25 §25.5.5: Class B lap splice = 1.3 × ld.
                # Use calculate_development_length when material data is available; otherwise fall back to 40db.
                if mat is not None:
                    bar_size = f"D{int(db_main)}"
                    ld_m = self.aci.calculate_development_length(
                        bar_size, mat.fc_prime, mat.fy) / 1000.0  # m
                    lap_m = 1.3 * ld_m
                else:
                    lap_m = 40.0 * db_main / 1000.0  # fallback: flat 40db
                req_len_s = L_m + lap_m
                stock_txt_s, ordered_m_s = get_best_commercial_order(req_len_s, num_spliced, db_main)
                weight_s = ordered_m_s * ((db_main ** 2) / 162.0)
                total_kg += weight_s
                rows.append(
                    QTORow("Main Long. (Spliced)", f"D{int(db_main)}", num_spliced, req_len_s, stock_txt_s, weight_s))

            if num_unspliced > 0:
                req_len_u = L_m
                stock_txt_u, ordered_m_u = get_best_commercial_order(req_len_u, num_unspliced, db_main)
                weight_u = ordered_m_u * ((db_main ** 2) / 162.0)
                total_kg += weight_u
                rows.append(QTORow("Main Long. (Unspliced)", f"D{int(db_main)}", num_unspliced, req_len_u, stock_txt_u,
                                   weight_u))

        s_m = max(res.reinforcement.tie_spacing, 50.0) / 1000.0
        total_stirrups = math.ceil(L_m / s_m)
        if total_stirrups > 0:
            db_t = get_db(res.reinforcement.tie_bars)
            c_m = geom.cover / 1000.0
            lx, ly = res.reinforcement.tie_legs_x, res.reinforcement.tie_legs_y
            # ACI 318M-25 §25.3.2: seismic hook extension = max(6db, 75 mm) per leg end.
            hook_tail_m = max(6.0 * db_t, 75.0) / 1000.0  # metres
            # Perimeter of closed tie + one hook extension per crosstie leg
            tie_len_m = (2 * (b_m - 2 * c_m) + 2 * (h_m - 2 * c_m) + 2 * hook_tail_m) + (
                        max(0, ly - 2) * (h_m - 2 * c_m + 2 * hook_tail_m) + max(0, lx - 2) * (
                            b_m - 2 * c_m + 2 * hook_tail_m))
            num_12m = math.ceil((total_stirrups * tie_len_m) / 12.0)
            weight = num_12m * 12.0 * ((db_t ** 2) / 162.0)
            total_kg += weight
            rows.append(
                QTORow(f"Ties ({lx}x{ly} legs)", f"D{int(db_t)}", total_stirrups, tie_len_m, f"{num_12m} x 12.0m",
                       weight))

        return QTOResult(vol_concrete, area_formwork, total_kg, rows)