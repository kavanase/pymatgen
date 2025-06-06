from __future__ import annotations

import os

import numpy as np
import pytest
from numpy.testing import assert_allclose

from pymatgen.core.structure import Lattice, Molecule, Structure
from pymatgen.io.feff.inputs import Atoms, Header, Potential, Tags
from pymatgen.io.feff.sets import FEFFDictSet, MPELNESSet, MPEXAFSSet, MPXANESSet
from pymatgen.util.testing import TEST_FILES_DIR, MatSciTest

FEFF_TEST_DIR = f"{TEST_FILES_DIR}/io/feff"


class TestFeffInputSet(MatSciTest):
    @classmethod
    def setup_class(cls):
        cls.header_string = """* This FEFF.inp file generated by pymatgen
TITLE comment: From cif file
TITLE Source:  CoO19128.cif
TITLE Structure Summary:  Co2 O2
TITLE Reduced formula:  CoO
TITLE space group: (P6_3mc), space number:  (186)
TITLE abc:  3.297078   3.297078   5.254213
TITLE angles: 90.000000  90.000000 120.000000
TITLE sites: 4
* 1 Co     0.333333     0.666667     0.503676
* 2 Co     0.666667     0.333333     0.003676
* 3 O     0.333333     0.666667     0.121324
* 4 O     0.666667     0.333333     0.621325"""
        cif_file = f"{TEST_FILES_DIR}/cif/CoO19128.cif"
        cls.structure = Structure.from_file(cif_file, primitive=True)
        cls.absorbing_atom = "O"
        cls.mp_xanes = MPXANESSet(cls.absorbing_atom, cls.structure)

    def test_get_header(self):
        comment = "From cif file"
        header = str(self.mp_xanes.header(source="CoO19128.cif", comment=comment))

        ref = self.header_string.splitlines()
        last4 = [" ".join(line.split()[2:]) for line in ref[-4:]]
        for idx, line in enumerate(header.splitlines()):
            if idx < 9:
                assert line == ref[idx]
            else:
                assert " ".join(line.split()[2:]) in last4

    def test_get_feff_tags(self):
        tags = self.mp_xanes.tags.as_dict()
        assert tags["COREHOLE"] == "FSR", "Failed to generate PARAMETERS string"

    def test_get_feff_pot(self):
        potential = str(self.mp_xanes.potential)
        dct, dr = Potential.pot_dict_from_str(potential)
        assert dct["Co"] == 1, "Wrong symbols read in for Potential"
        assert dr == {0: "O", 1: "Co", 2: "O"}

    def test_get_feff_atoms(self):
        atoms = str(self.mp_xanes.atoms)
        assert atoms.splitlines()[3].split()[4] == self.absorbing_atom, "failed to create ATOMS string"

    def test_to_and_from_dict(self):
        dct = self.mp_xanes.as_dict()
        xanes_set = MPXANESSet.from_dict(dct)
        assert dct == xanes_set.as_dict(), "round trip as_dict failed"

    def test_user_tag_settings(self):
        tags_dict_ans = self.mp_xanes.tags.as_dict()
        tags_dict_ans["COREHOLE"] = "RPA"
        tags_dict_ans["EDGE"] = "L1"
        user_tag_settings = {"COREHOLE": "RPA", "EDGE": "L1"}
        mp_xanes_2 = MPXANESSet(self.absorbing_atom, self.structure, user_tag_settings=user_tag_settings)
        assert mp_xanes_2.tags.as_dict() == tags_dict_ans

    def test_eels_to_from_dict(self):
        elnes_set = MPELNESSet(
            self.absorbing_atom,
            self.structure,
            radius=5.0,
            beam_energy=100,
            beam_direction=[1, 0, 0],
            collection_angle=7,
            convergence_angle=6,
        )
        elnes_dict = elnes_set.as_dict()
        elnes_2 = MPELNESSet.from_dict(elnes_dict)
        assert elnes_dict == elnes_2.as_dict()

    def test_eels_tags_set(self):
        radius = 5.0
        user_eels_settings = {
            "ENERGY": "4 0.04 0.1",
            "BEAM_ENERGY": "200 1 0 1",
            "ANGLES": "2 3",
        }
        elnes = MPELNESSet(
            self.absorbing_atom,
            self.structure,
            radius=radius,
            user_eels_settings=user_eels_settings,
        )
        elnes_2 = MPELNESSet(
            self.absorbing_atom,
            self.structure,
            radius=radius,
            beam_energy=100,
            beam_direction=[1, 0, 0],
            collection_angle=7,
            convergence_angle=6,
        )
        assert elnes.tags["ELNES"]["ENERGY"] == user_eels_settings["ENERGY"]
        assert elnes.tags["ELNES"]["BEAM_ENERGY"] == user_eels_settings["BEAM_ENERGY"]
        assert elnes.tags["ELNES"]["ANGLES"] == user_eels_settings["ANGLES"]
        assert elnes_2.tags["ELNES"]["BEAM_ENERGY"] == [100, 0, 1, 1]
        assert elnes_2.tags["ELNES"]["BEAM_DIRECTION"] == [1, 0, 0]
        assert elnes_2.tags["ELNES"]["ANGLES"] == [7, 6]

    def test_charged_structure(self):
        # one Zn+2, 9 triflate, plus water
        # Molecule, net charge of -7
        xyz = f"{FEFF_TEST_DIR}/feff_radial_shell.xyz"
        mol = Molecule.from_file(xyz)
        mol.set_charge_and_spin(-7)
        # Zn should not appear in the pot_dict
        with pytest.warns(UserWarning, match="ION tags"):
            MPXANESSet("Zn", mol)
        struct = self.structure.copy()
        struct.set_charge(1)
        with pytest.raises(ValueError, match="not supported"):
            MPXANESSet("Co", struct)

    def test_reciprocal_tags_and_input(self):
        user_tag_settings = {"RECIPROCAL": "", "KMESH": "1000"}
        elnes = MPELNESSet(self.absorbing_atom, self.structure, user_tag_settings=user_tag_settings)
        assert "RECIPROCAL" in elnes.tags
        assert elnes.tags["TARGET"] == 3
        assert elnes.tags["KMESH"] == "1000"
        assert elnes.tags["CIF"] == "Co2O2.cif"
        assert elnes.tags["COREHOLE"] == "RPA"
        all_input = elnes.all_input()
        assert "ATOMS" not in all_input
        assert "POTENTIALS" not in all_input
        elnes.write_input(output_dir=self.tmp_path)
        structure = Structure.from_file("Co2O2.cif")
        assert self.structure.matches(structure)
        assert {*os.listdir()} == {"Co2O2.cif", "HEADER", "PARAMETERS", "feff.inp"}

    def test_small_system_exafs(self):
        exafs_settings = MPEXAFSSet(self.absorbing_atom, self.structure)
        assert not exafs_settings.small_system
        assert "RECIPROCAL" not in exafs_settings.tags

        user_tag_settings = {"RECIPROCAL": ""}
        exafs_settings_2 = MPEXAFSSet(
            self.absorbing_atom,
            self.structure,
            nkpts=1000,
            user_tag_settings=user_tag_settings,
        )
        assert not exafs_settings_2.small_system
        assert "RECIPROCAL" not in exafs_settings_2.tags

    def test_number_of_kpoints(self):
        user_tag_settings = {"RECIPROCAL": ""}
        elnes = MPELNESSet(
            self.absorbing_atom,
            self.structure,
            nkpts=1000,
            user_tag_settings=user_tag_settings,
        )
        assert elnes.tags["KMESH"] == [12, 12, 7]

    def test_large_systems(self):
        struct = Structure.from_file(f"{TEST_FILES_DIR}/cif/La4Fe4O12.cif")
        user_tag_settings = {"RECIPROCAL": "", "KMESH": "1000"}
        elnes = MPELNESSet("Fe", struct, user_tag_settings=user_tag_settings)
        assert "RECIPROCAL" not in elnes.tags
        assert "KMESH" not in elnes.tags
        assert "CIF" not in elnes.tags
        assert "TARGET" not in elnes.tags

    def test_post_feffset(self):
        self.mp_xanes.write_input(f"{self.tmp_path}/xanes_3")
        feff_dict_input = FEFFDictSet.from_directory(f"{self.tmp_path}/xanes_3")
        assert feff_dict_input.tags == Tags.from_file(f"{self.tmp_path}/xanes_3/feff.inp")
        assert str(feff_dict_input.header()) == str(Header.from_file(f"{self.tmp_path}/xanes_3/HEADER"))
        feff_dict_input.write_input(f"{self.tmp_path}/xanes_3_regen")
        origin_tags = Tags.from_file(f"{self.tmp_path}/xanes_3/PARAMETERS")
        output_tags = Tags.from_file(f"{self.tmp_path}/xanes_3_regen/PARAMETERS")
        origin_mole = Atoms.cluster_from_file(f"{self.tmp_path}/xanes_3/feff.inp")
        output_mole = Atoms.cluster_from_file(f"{self.tmp_path}/xanes_3_regen/feff.inp")
        original_mole_dist = np.array(origin_mole.distance_matrix[0, :])
        output_mole_dist = np.array(output_mole.distance_matrix[0, :])
        original_mole_shell = [x.species_string for x in origin_mole]
        output_mole_shell = [x.species_string for x in output_mole]

        assert_allclose(original_mole_dist, output_mole_dist, atol=1e-4)
        assert origin_tags == output_tags
        assert original_mole_shell == output_mole_shell

        reci_mp_xanes = MPXANESSet(self.absorbing_atom, self.structure, user_tag_settings={"RECIPROCAL": ""})
        reci_mp_xanes.write_input(f"{self.tmp_path}/xanes_reci")
        feff_reci_input = FEFFDictSet.from_directory(f"{self.tmp_path}/xanes_reci")
        assert "RECIPROCAL" in feff_reci_input.tags

        feff_reci_input.write_input(f"{self.tmp_path}/Dup_reci")
        assert os.path.isfile(f"{self.tmp_path}/Dup_reci/HEADER")
        assert os.path.isfile(f"{self.tmp_path}/Dup_reci/feff.inp")
        assert os.path.isfile(f"{self.tmp_path}/Dup_reci/PARAMETERS")
        assert not os.path.isfile(f"{self.tmp_path}/Dup_reci/ATOMS")
        assert not os.path.isfile(f"{self.tmp_path}/Dup_reci/POTENTIALS")

        tags_original = Tags.from_file(f"{self.tmp_path}/xanes_reci/feff.inp")
        tags_output = Tags.from_file(f"{self.tmp_path}/Dup_reci/feff.inp")
        assert tags_original == tags_output

        struct_orig = Structure.from_file(f"{self.tmp_path}/xanes_reci/Co2O2.cif")
        struct_reci = Structure.from_file(f"{self.tmp_path}/Dup_reci/Co2O2.cif")
        assert struct_orig == struct_reci

    def test_post_dist_diff(self):
        feff_dict_input = FEFFDictSet.from_directory(f"{FEFF_TEST_DIR}/feff_dist_test")
        assert feff_dict_input.tags == Tags.from_file(f"{FEFF_TEST_DIR}/feff_dist_test/feff.inp")
        assert str(feff_dict_input.header()) == str(Header.from_file(f"{FEFF_TEST_DIR}/feff_dist_test/HEADER"))
        feff_dict_input.write_input(f"{self.tmp_path}/feff_dist_regen")
        origin_tags = Tags.from_file(f"{FEFF_TEST_DIR}/feff_dist_test/PARAMETERS")
        output_tags = Tags.from_file(f"{self.tmp_path}/feff_dist_regen/PARAMETERS")
        origin_mole = Atoms.cluster_from_file(f"{FEFF_TEST_DIR}/feff_dist_test/feff.inp")
        output_mole = Atoms.cluster_from_file(f"{self.tmp_path}/feff_dist_regen/feff.inp")
        original_mole_dist = np.array(origin_mole.distance_matrix[0, :])
        output_mole_dist = np.array(output_mole.distance_matrix[0, :])
        original_mole_shell = [x.species_string for x in origin_mole]
        output_mole_shell = [x.species_string for x in output_mole]

        assert_allclose(original_mole_dist, output_mole_dist, atol=1e-4)
        assert origin_tags == output_tags
        assert original_mole_shell == output_mole_shell

    def test_big_radius(self):
        struct = Structure.from_spacegroup("Pm-3m", Lattice.cubic(3.033043), ["Ti", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
        dict_set = FEFFDictSet(
            absorbing_atom="Ti",
            structure=struct,
            radius=10.0,
            config_dict={
                "S02": "0",
                "COREHOLE": "regular",
                "CONTROL": "1 1 1 1 1 1",
                "XANES": "4 0.04 0.1",
                "SCF": "7.0 0 100 0.2 3",
                "FMS": "9.0 0",
                "EXCHANGE": "0 0.0 0.0 2",
                "RPATH": "-1",
            },
        )
        assert str(dict_set).startswith(
            "EXAFS\nS02 = 0\nCOREHOLE = regular\nCONTROL = 1 1 1 1 1 1\nXANES = 4 0.04 0.1\nSCF = 7.0 0 100 0.2 3\n"
            "FMS = 9.0 0\nEXCHANGE = 0 0.0 0.0 2\nRPATH = -1\nEDGE = K\n"
        )

    def test_cluster_index(self):
        # https://github.com/materialsproject/pymatgen/pull/3256
        cif_file = f"{TEST_FILES_DIR}/cif/Fe3O4.cif"
        structure = Structure.from_file(cif_file)
        for idx in range(len(structure.species)):
            assert Atoms(structure, idx, 3).cluster
