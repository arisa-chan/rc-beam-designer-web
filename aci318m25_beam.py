# -*- coding: utf-8 -*-

"""
ACI 318M-25 Beam Design Library
Building Code Requirements for Structural Concrete - Beam Design
"""

import math
from typing import Dict, Tuple, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
from aci318m25 import ACI318M25, ConcreteStrengthClass, ReinforcementGrade, MaterialProperties

class BeamType(Enum):
    RECTANGULAR = "rectangular"
    T_BEAM = "t_beam"
    L_BEAM = "l_beam"
    INVERTED_T = "inverted_t"

class LoadType(Enum):
    POINT_LOAD = "point_load"
    UNIFORMLY_DISTRIBUTED = "uniformly_distributed"
    TRIANGULAR = "triangular"
    TRAPEZOIDAL = "trapezoidal"

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
class BeamGeometry:
    length: float
    width: float
    height: float
    effective_depth: float
    cover: float
    flange_width: float
    flange_thickness: float
    beam_type: BeamType
    clear_span: float = 0.0
    sdc: SeismicDesignCategory = SeismicDesignCategory.A
    frame_system: FrameSystem = FrameSystem.ORDINARY

@dataclass
class ReinforcementDesign:
    main_bars: List[str]
    main_area: float
    compression_bars: List[str]
    compression_area: float
    stirrups: str
    stirrup_spacing: float
    development_length: float
    stirrup_spacing_hinge: float = 0.0
    hinge_length: float = 0.0
    torsion_longitudinal_area: float = 0.0
    torsion_required: bool = False

@dataclass
class BeamAnalysisResult:
    moment_capacity: float
    probable_moment: float
    shear_capacity: float
    capacity_shear_ve: float
    torsion_capacity: float
    deflection: float
    crack_width: float
    reinforcement: ReinforcementDesign
    utilization_ratio: float
    design_notes: List[str]

class ACI318M25BeamDesign:
    
    def __init__(self):
        self.aci = ACI318M25()
        self.phi_factors = {'flexure_tension_controlled': 0.90, 'flexure_compression_controlled_tied': 0.65, 'shear': 0.75, 'torsion': 0.75, 'seismic_joint_shear': 0.85}

    def _parse_stirrup(self, stirrup_str: str) -> Tuple[int, str]:
        if stirrup_str == 'None': return 0, 'D10'
        if "-leg " in stirrup_str:
            parts = stirrup_str.split('-leg ')
            return int(parts[0]), parts[1]
        return 2, stirrup_str

    def check_seismic_geometric_limits(self, geometry: BeamGeometry) -> List[str]:
        warnings = []
        if geometry.frame_system == FrameSystem.SPECIAL:
            if geometry.clear_span > 0 and (geometry.clear_span / geometry.effective_depth) < 4.0: warnings.append("SMF Violation: Clear span to depth ratio must be >= 4.0.")
            if geometry.width < 250.0: warnings.append(f"SMF Violation: Beam width ({geometry.width:.0f} mm) must be >= 250 mm.")
            if (geometry.width / geometry.height) < 0.3: warnings.append("SMF Violation: Beam width to overall depth ratio must be >= 0.3.")
        return warnings

    def _calculate_torsional_properties(self, beam_geometry: BeamGeometry, stirrup_size: str = 'D10') -> Dict[str, float]:
        _, actual_stirrup_sz = self._parse_stirrup(stirrup_size)
        bw, h, cover = beam_geometry.width, beam_geometry.height, beam_geometry.cover
        db_stirrup = self.aci.get_bar_diameter(actual_stirrup_sz)
        
        Acp, pcp = bw * h, 2 * (bw + h)
        x1, y1 = bw - 2 * cover - db_stirrup, h - 2 * cover - db_stirrup
        if x1 <= 0 or y1 <= 0: raise ValueError("Beam dimensions too small for cover and stirrups.")
        Aoh, ph = x1 * y1, 2 * (x1 + y1)
        Ao = 0.85 * Aoh
        return {'Acp': Acp, 'pcp': pcp, 'Aoh': Aoh, 'ph': ph, 'Ao': Ao}

    def check_torsion_requirement(self, tu: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> bool:
        if tu <= 0.0: return False
        props = self._calculate_torsional_properties(beam_geometry)
        Tth = 0.083 * math.sqrt(material_props.fc_prime) * (props['Acp']**2 / props['pcp']) / 1e6
        return tu > (self.phi_factors['torsion'] * Tth)

    def calculate_probable_moment_capacity(self, As: float, As_prime: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> float:
        fc_prime, fy_pr = material_props.fc_prime, 1.25 * material_props.fy
        b, d, d_prime = beam_geometry.width, beam_geometry.effective_depth, beam_geometry.cover + 20.0
        a = max(0.01, (As * fy_pr - As_prime * fy_pr) / (0.85 * fc_prime * b))
        return max(0.0, (As * fy_pr * (d - a/2) + As_prime * fy_pr * (a/2 - d_prime)) / 1e6)

    def calculate_minimum_reinforcement_ratio(self, fc_prime: float, fy: float) -> float:
        return max(1.4 / fy, 0.25 * math.sqrt(fc_prime) / fy)
    
    def calculate_maximum_reinforcement_ratio(self, fc_prime: float, fy: float, beam_geometry: BeamGeometry) -> float:
        beta1 = self._calculate_beta1(fc_prime)
        rho_max = 3/8 * 0.85 * fc_prime * beta1 / fy
        return min(rho_max, 0.025) if beam_geometry.frame_system == FrameSystem.SPECIAL else rho_max
    
    def design_flexural_reinforcement(self, mu: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> Tuple[ReinforcementDesign, List[str]]:
        notes = []
        fc_prime, fy = material_props.fc_prime, material_props.fy
        b, d, Mu = beam_geometry.width, beam_geometry.effective_depth, mu * 1e6
        
        As_max = self.calculate_maximum_reinforcement_ratio(fc_prime, fy, beam_geometry) * b * d
        a_max = As_max * fy / (0.85 * fc_prime * b)
        if Mu <= self.phi_factors['flexure_tension_controlled'] * (As_max * fy * (d - a_max / 2)):
            design = self._design_tension_reinforcement_only(Mu, beam_geometry, material_props)
        else:
            design = self._design_doubly_reinforced_section(Mu, beam_geometry, material_props)
            notes.append("Compression reinforcement was required to satisfy flexural demand.")
            
        if beam_geometry.frame_system == FrameSystem.SPECIAL:
            notes.append("SMF Detailing: Ensure at least two continuous bars are provided top and bottom.")
            required_mn_secondary = 0.5 * self._calculate_moment_capacity(design.main_area, beam_geometry, material_props)
            mn_provided_secondary = self._calculate_moment_capacity(design.compression_area, beam_geometry, material_props) if design.compression_area > 0 else 0.0
            if mn_provided_secondary < required_mn_secondary:
                design.compression_area = max((required_mn_secondary * 1e6) / (fy * 0.9 * d), self.calculate_minimum_reinforcement_ratio(fc_prime, fy) * b * d)
                design.compression_bars = self._select_reinforcement_bars(design.compression_area, beam_geometry, fy, 'D10')
                notes.append(f"SMF Integrity: Opposite face reinforcement increased to {design.compression_area:.1f} mm².")
                
        return design, notes
    
    def _design_tension_reinforcement_only(self, Mu: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> ReinforcementDesign:
        fc_prime, fy = material_props.fc_prime, material_props.fy
        b, d, phi = beam_geometry.width, beam_geometry.effective_depth, self.phi_factors['flexure_tension_controlled']
        A, B, C = phi * fy**2 / (2 * 0.85 * fc_prime * b), -phi * fy * d, Mu
        discriminant = B**2 - 4*A*C
        if discriminant < 0: raise ValueError("Section dimensions inadequate for applied flexural moment.")
        
        As_required = max((-B - math.sqrt(discriminant)) / (2*A), self.calculate_minimum_reinforcement_ratio(fc_prime, fy) * b * d)
        main_bars = self._select_reinforcement_bars(As_required, beam_geometry, fy, 'D10')
        ld = self.aci.calculate_development_length(main_bars[0] if main_bars else 'D20', fc_prime, fy)
        return ReinforcementDesign(main_bars=main_bars, main_area=As_required, compression_bars=[], compression_area=0.0, stirrups='D10', stirrup_spacing=200.0, development_length=ld)
    
    def _design_doubly_reinforced_section(self, Mu: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> ReinforcementDesign:
        fc_prime, fy, es = material_props.fc_prime, material_props.fy, material_props.es
        b, d, d_prime, phi = beam_geometry.width, beam_geometry.effective_depth, beam_geometry.cover + 20, self.phi_factors['flexure_tension_controlled']
        As1 = self.calculate_maximum_reinforcement_ratio(fc_prime, fy, beam_geometry) * b * d
        a1 = As1 * fy / (0.85 * fc_prime * b)
        Mu2 = Mu - phi * (As1 * fy * (d - a1/2))
        
        c = a1 / self._calculate_beta1(fc_prime)
        fs_prime = max(0.0, min(0.003 * (c - d_prime) / c * es, fy))
        if fs_prime <= 0.0: raise ValueError("Compression steel is in tension zone. Resize section.")
        
        As2_prime = Mu2 / (phi * fs_prime * (d - d_prime))
        As_total = As1 + (As2_prime * (fs_prime / fy))
        
        main_bars = self._select_reinforcement_bars(As_total, beam_geometry, fy, 'D10')
        comp_bars = self._select_reinforcement_bars(As2_prime, beam_geometry, fy, 'D10')
        ld = self.aci.calculate_development_length(main_bars[0] if main_bars else 'D25', fc_prime, fy)
        return ReinforcementDesign(main_bars=main_bars, main_area=As_total, compression_bars=comp_bars, compression_area=As2_prime, stirrups='D10', stirrup_spacing=150.0, development_length=ld)
    
    def design_transverse_reinforcement(self, vu: float, tu: float, mpr: float, gravity_shear: float, beam_geometry: BeamGeometry, material_props: MaterialProperties, main_reinforcement: ReinforcementDesign) -> Tuple[str, float, float, float, float, float, List[str]]:
        notes = []
        fc_prime, fy, fyt = material_props.fc_prime, material_props.fy, material_props.fyt 
        bw, d = beam_geometry.width, beam_geometry.effective_depth
        phi_v, phi_t = self.phi_factors['shear'], self.phi_factors['torsion']
        
        Vu, Tu, Ve = vu * 1000, tu * 1e6, vu * 1000
        if beam_geometry.frame_system == FrameSystem.SPECIAL and beam_geometry.clear_span > 0:
            Ve = max((gravity_shear * 1000) + ((2 * mpr * 1e6) / beam_geometry.clear_span), Vu)
            notes.append(f"SMF Capacity Design: Seismic shear Ve = {Ve/1000:.1f} kN")
            
        Vc = 0.17 * math.sqrt(fc_prime) * bw * d
        if beam_geometry.frame_system == FrameSystem.SPECIAL and (Ve - gravity_shear * 1000) > 0.5 * Ve:
            Vc = 0.0
            notes.append("SMF Detailing: Vc = 0")
            
        Vs_req = max(0.0, (Ve / phi_v) - Vc)
        Av_over_s = Vs_req / (fyt * d)
        
        torsion_required = self.check_torsion_requirement(tu, beam_geometry, material_props)
        props = self._calculate_torsional_properties(beam_geometry)
        At_over_s, Al_req = 0.0, 0.0
        
        if torsion_required:
            notes.append("Torsion demand exceeds threshold. Combined shear-torsion active.")
            combined_stress = math.sqrt((Ve / (bw * d))**2 + ((Tu * props['ph']) / (1.7 * props['Aoh']**2))**2)
            stress_limit = phi_v * ((0.17 * math.sqrt(fc_prime)) + 0.66 * math.sqrt(fc_prime))
            if combined_stress > stress_limit: notes.append(f"CRITICAL: Section inadequate for combined shear/torsion.")

            theta = math.radians(45)
            At_over_s = Tu / (phi_t * 2 * props['Ao'] * fyt * (1 / math.tan(theta)))
            
            # Correctly utilizes fyt/fy ratio for Al calculation
            At_over_s_min = max(At_over_s, 0.175 * bw / fyt)
            Al_req = max(At_over_s * props['ph'] * (fyt / fy) * (1 / math.tan(theta))**2, (0.42 * math.sqrt(fc_prime) * props['Acp'] / fy) - (At_over_s_min * props['ph'] * (fyt / fy)), 0.0)

        min_transverse = max(0.062 * math.sqrt(fc_prime) * bw / fyt, 0.35 * bw / fyt)

        sizes, max_legs = ['D10', 'D12', 'D16'], max(2, min(6, math.floor((bw - 2 * beam_geometry.cover) / 80) + 1))
        best_size, best_legs, s_req, found = 'D10', 2, float('inf'), False
        
        for size in sizes:
            A_bar = self.aci.get_bar_area(size)
            for n in range(2, max_legs + 1):
                denom = At_over_s + (Av_over_s / n)
                s_demand = A_bar / denom if denom > 0 else float('inf')
                s_calc = min(s_demand, (n * A_bar) / min_transverse if min_transverse > 0 else float('inf'))
                if s_calc >= 75.0:
                    best_size, best_legs, s_req, found = size, n, s_calc, True
                    break
            if found: break
                
        if not found:
            best_size, best_legs = 'D16', max_legs
            denom = At_over_s + (Av_over_s / best_legs)
            s_req = self.aci.get_bar_area(best_size) / denom if denom > 0 else 50.0
            
        stirrup_size = f"{best_legs}-leg {best_size}" if best_legs > 2 else best_size

        Vs_actual = max(0.0, Ve / phi_v - Vc)
        s_span_max = min(d / 4, 300.0) if Vs_actual > (0.33 * math.sqrt(fc_prime) * bw * d) else min(d / 2, 600.0)
        if torsion_required: s_span_max = min(s_span_max, props['ph'] / 8, 300.0)
        
        s_hinge_max = min(d / 4, 6 * self.aci.get_bar_diameter(main_reinforcement.main_bars[0] if main_reinforcement.main_bars else 'D20'), 150.0) if beam_geometry.frame_system == FrameSystem.SPECIAL else s_span_max 
            
        s_hinge_actual = math.floor(min(s_req, s_hinge_max) / 10) * 10
        s_span_actual = math.floor(min(s_req, s_span_max) / 10) * 10

        Tn_provided = 0.0
        if torsion_required and s_span_actual > 0:
            Tn_provided = (2 * props['Ao'] * self.aci.get_bar_area(best_size) * fyt * (1 / math.tan(math.radians(45))) / s_span_actual) / 1e6

        return stirrup_size, max(s_hinge_actual, 50.0), max(s_span_actual, 50.0), Ve / 1000, Al_req, Tn_provided, notes
    
    def perform_complete_beam_design(self, mu: float, vu: float, beam_geometry: BeamGeometry, material_props: MaterialProperties, service_moment: float = None, tu: float = 0.0, gravity_shear: float = 0.0) -> BeamAnalysisResult:
        design_notes = self.check_seismic_geometric_limits(beam_geometry)
        
        flexural_design, flex_notes = self.design_flexural_reinforcement(mu, beam_geometry, material_props)
        design_notes.extend(flex_notes)
        
        mpr = self.calculate_probable_moment_capacity(flexural_design.main_area, flexural_design.compression_area, beam_geometry, material_props) if beam_geometry.frame_system == FrameSystem.SPECIAL else 0.0
        
        gravity_v = gravity_shear if gravity_shear > 0 else vu * 0.5 
        stirrup_size, s_hinge, s_span, ve_design, al_req, tn_cap, trans_notes = self.design_transverse_reinforcement(vu, tu, mpr, gravity_v, beam_geometry, material_props, flexural_design)
        design_notes.extend(trans_notes)
        
        flexural_design.stirrups, flexural_design.stirrup_spacing_hinge, flexural_design.stirrup_spacing = stirrup_size, s_hinge, s_span
        flexural_design.hinge_length = 2 * beam_geometry.height if beam_geometry.frame_system == FrameSystem.SPECIAL else 0.0
        flexural_design.torsion_required, flexural_design.torsion_longitudinal_area = al_req > 0, al_req

        moment_capacity = self._calculate_moment_capacity(flexural_design.main_area, beam_geometry, material_props)
        shear_capacity = self._calculate_shear_capacity(beam_geometry, material_props, stirrup_size, s_hinge)
        
        util_m = mu / (self.phi_factors['flexure_tension_controlled'] * moment_capacity) if moment_capacity > 0 else 1.0
        util_v = ve_design / (self.phi_factors['shear'] * shear_capacity) if shear_capacity > 0 else 1.0
        util_t = tu / (self.phi_factors['torsion'] * tn_cap) if tn_cap > 0 else 0.0
        
        deflection = (5 * service_moment * 1e6 * beam_geometry.length**2) / (48 * material_props.ec * (beam_geometry.width * beam_geometry.height**3 / 12)) if service_moment else 0.0
            
        return BeamAnalysisResult(moment_capacity=moment_capacity, probable_moment=mpr, shear_capacity=shear_capacity, capacity_shear_ve=ve_design, torsion_capacity=tn_cap, deflection=deflection, crack_width=0.0, reinforcement=flexural_design, utilization_ratio=max(util_m, util_v, util_t), design_notes=design_notes)

    def _calculate_moment_capacity(self, As: float, beam_geometry: BeamGeometry, material_props: MaterialProperties) -> float:
        if As <= 0.0: return 0.0
        a = As * material_props.fy / (0.85 * material_props.fc_prime * beam_geometry.width)
        return max(0.0, As * material_props.fy * (beam_geometry.effective_depth - a/2) / 1e6)
        
    def _calculate_shear_capacity(self, beam_geometry: BeamGeometry, material_props: MaterialProperties, stirrup_size: str, spacing: float) -> float:
        Vc = 0.17 * math.sqrt(material_props.fc_prime) * beam_geometry.width * beam_geometry.effective_depth / 1000
        if stirrup_size != 'None' and spacing > 0:
            num_legs, actual_size = self._parse_stirrup(stirrup_size)
            Vs = num_legs * self.aci.get_bar_area(actual_size) * material_props.fyt * beam_geometry.effective_depth / spacing / 1000
        else: Vs = 0.0
        return Vc + Vs
        
    def _calculate_beta1(self, fc_prime: float) -> float:
        if fc_prime <= 28.0: return 0.85
        elif fc_prime <= 55.0: return 0.85 - 0.05 * (fc_prime - 28.0) / 7.0
        else: return 0.65

    def _select_reinforcement_bars(self, As_required: float, beam_geometry: BeamGeometry, fy: float, stirrup_size: str = 'D10', aggregate_size: float = 25.0) -> List[str]:
        if As_required <= 0: return []
        bar_data = [('D16', 201.06), ('D20', 314.16), ('D25', 490.87), ('D28', 615.75), ('D32', 804.25), ('D36', 1017.88)]
        _, actual_stirrup = self._parse_stirrup(stirrup_size)
        available_width = beam_geometry.width - 2 * beam_geometry.cover - 2 * self.aci.get_bar_diameter(actual_stirrup)
        
        for bar_size, area in bar_data:
            num_bars = max(2, math.ceil(As_required / area))
            db = self.aci.get_bar_diameter(bar_size)
            min_clear_spacing = max(25.0, db, (4.0/3.0) * aggregate_size)
            max_bars_per_layer = math.floor((available_width + min_clear_spacing) / (db + min_clear_spacing))
            if max_bars_per_layer >= 2 and math.ceil(num_bars / max_bars_per_layer) <= 2:
                return [bar_size] * num_bars
        return [bar_data[-1][0]] * max(2, math.ceil(As_required / bar_data[-1][1]))