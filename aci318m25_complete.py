# -*- coding: utf-8 -*-

"""
ACI 318M-25 Complete Member Design Library Manager
Central access point for all ACI 318M-25 structural member design libraries
"""

import math
from typing import Dict, Tuple, List, Optional, Union
from dataclasses import dataclass
from enum import Enum

from aci318m25 import ACI318M25, ConcreteStrengthClass, ReinforcementGrade, MaterialProperties
from aci318m25_beam import ACI318M25BeamDesign, BeamGeometry, BeamType
# Note: Ensure these local imports match your other physical files:
# from aci318m25_column import ACI318M25ColumnDesign, ColumnGeometry, ColumnLoads, ColumnType, ColumnShape, LoadCondition
# from aci318m25_slab import ACI318M25SlabDesign, SlabGeometry, SlabLoads, SlabType, SupportCondition, LoadPattern
# from aci318m25_footing import ACI318M25FootingDesign, FootingLoads, SoilProperties, FootingType, SoilCondition
# from aci318m25_wall import ACI318M25WallDesign, WallGeometry, WallLoads, WallType, WallSupportCondition, LoadType
# from aci318m25_diaphragm import ACI318M25DiaphragmDesign, DiaphragmGeometry, DiaphragmLoads, DiaphragmType, DiaphragmLoadType

class StructuralMemberType(Enum):
    BEAM = "beam"
    COLUMN = "column"
    SLAB = "slab"
    FOOTING = "footing"
    WALL = "wall"
    DIAPHRAGM = "diaphragm"

@dataclass
class ProjectInfo:
    project_name: str
    location: str
    date: str
    engineer: str
    client: str = ""
    description: str = ""

class ACI318M25MemberLibrary:
    
    def __init__(self):
        self.aci = ACI318M25()
        self.beam_design = ACI318M25BeamDesign()
        # Initialize others if you have them in the same directory
        
        self.default_materials = {
            'concrete': ConcreteStrengthClass.FC28,
            'steel': ReinforcementGrade.GRADE420,
            'transverse_steel': ReinforcementGrade.GRADE420 # Distinct default for stirrups
        }
        
        self.version = "1.0"
        self.code_version = "ACI 318M-25"
        
    def get_library_info(self) -> Dict[str, str]:
        return {
            'version': self.version,
            'code': self.code_version,
            'units': 'SI (MPa, kN, mm, m)'
        }
    
    def get_available_materials(self) -> Dict[str, List[str]]:
        return {
            'concrete_strengths': [grade.value for grade in ConcreteStrengthClass],
            'steel_grades': [grade.value for grade in ReinforcementGrade]
        }
    
    def create_standard_material_properties(self, 
                                          concrete_class: ConcreteStrengthClass = None,
                                          steel_grade: ReinforcementGrade = None,
                                          transverse_steel_grade: ReinforcementGrade = None) -> MaterialProperties:
        """Create standard material properties capturing both main and transverse grades"""
        if concrete_class is None: concrete_class = self.default_materials['concrete']
        if steel_grade is None: steel_grade = self.default_materials['steel']
        if transverse_steel_grade is None: transverse_steel_grade = self.default_materials['transverse_steel']
        
        return self.aci.get_material_properties(concrete_class, steel_grade, transverse_steel_grade)