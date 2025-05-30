from __future__ import annotations

import math
import pickle
import re
from copy import deepcopy
from enum import Enum

import numpy as np
import pytest
from pytest import approx

from pymatgen.core import DummySpecies, Element, Species, get_el_sp
from pymatgen.core.periodic_table import ElementBase, ElementType
from pymatgen.core.units import Ha_to_eV
from pymatgen.io.core import ParseError
from pymatgen.util.testing import MatSciTest


class TestElement(MatSciTest):
    def test_init(self):
        assert Element("Fe").symbol == "Fe"

        fictional_symbols = ("Dolphin", "Tyrannosaurus", "Zebra")

        for sym in fictional_symbols:
            with pytest.raises(ValueError, match=f"{sym!r} is not a valid Element"):
                Element(sym)

        assert id(Element("Fe")) == id(Element("Fe"))  # Test caching

    def test_iter(self):
        # Make sure isotopes don't show during iteration
        assert [elem.name for elem in Element] == (
            "H,He,Li,Be,B,C,N,O,F,Ne,Na,Mg,Al,Si,P,S,Cl,Ar,K,Ca,Sc,Ti,V,Cr,"
            "Mn,Fe,Co,Ni,Cu,Zn,Ga,Ge,As,Se,Br,Kr,Rb,Sr,Y,Zr,Nb,Mo,Tc,Ru,Rh,Pd,"
            "Ag,Cd,In,Sn,Sb,Te,I,Xe,Cs,Ba,La,Ce,Pr,Nd,Pm,Sm,Eu,Gd,Tb,Dy,Ho,Er,Tm,"
            "Yb,Lu,Hf,Ta,W,Re,Os,Ir,Pt,Au,Hg,Tl,Pb,Bi,Po,At,Rn,Fr,Ra,Ac,Th,Pa,U,Np,"
            "Pu,Am,Cm,Bk,Cf,Es,Fm,Md,No,Lr,Rf,Db,Sg,Bh,Hs,Mt,Ds,Rg,Cn,Nh,Fl,Mc,Lv,Ts,Og"
        ).split(",")

        # Make sure isotopes are still in members
        assert list(Element.__members__) == (
            "H,D,T,He,Li,Be,B,C,N,O,F,Ne,Na,Mg,Al,Si,P,S,Cl,Ar,K,Ca,Sc,Ti,V,Cr,"
            "Mn,Fe,Co,Ni,Cu,Zn,Ga,Ge,As,Se,Br,Kr,Rb,Sr,Y,Zr,Nb,Mo,Tc,Ru,Rh,Pd,"
            "Ag,Cd,In,Sn,Sb,Te,I,Xe,Cs,Ba,La,Ce,Pr,Nd,Pm,Sm,Eu,Gd,Tb,Dy,Ho,Er,Tm,"
            "Yb,Lu,Hf,Ta,W,Re,Os,Ir,Pt,Au,Hg,Tl,Pb,Bi,Po,At,Rn,Fr,Ra,Ac,Th,Pa,U,Np,"
            "Pu,Am,Cm,Bk,Cf,Es,Fm,Md,No,Lr,Rf,Db,Sg,Bh,Hs,Mt,Ds,Rg,Cn,Nh,Fl,Mc,Lv,Ts,Og"
        ).split(",")

    def test_missing_and_confusing_data(self):
        with pytest.warns(UserWarning, match="No data available"):
            _ = Element.H.metallic_radius
        with pytest.warns(UserWarning, match="No data available"):
            _ = Element.Og.ionization_energy

    def test_is_metal(self):
        for metal in ["Fe", "Eu", "Li", "Ca", "In"]:
            assert Element(metal).is_metal
        for non_metal in ["Ge", "Si", "O", "He"]:
            assert not Element(non_metal).is_metal

    def test_nan_x(self):
        assert math.isnan(Element.He.X)
        els = sorted([Element.He, Element.H, Element.F])
        assert els == [Element.H, Element.F, Element.He]

    def test_dict(self):
        fe = Element.Fe
        dct = fe.as_dict()
        assert fe == Element.from_dict(dct)

    def test_block(self):
        cases = {
            "O": "p",
            "Fe": "d",
            "Li": "s",
            "U": "f",
            "Er": "f",
            "Lu": "d",
            "Lr": "d",
        }
        for key, val in cases.items():
            assert Element(key).block == val

    def test_full_electronic_structure(self):
        cases = {
            "O": [(1, "s", 2), (2, "s", 2), (2, "p", 4)],
            "Fe": [
                (1, "s", 2),
                (2, "s", 2),
                (2, "p", 6),
                (3, "s", 2),
                (3, "p", 6),
                (4, "s", 2),
                (3, "d", 6),
            ],
            "Li": [(1, "s", 2), (2, "s", 1)],
            "U": [
                (1, "s", 2),
                (2, "s", 2),
                (2, "p", 6),
                (3, "s", 2),
                (3, "p", 6),
                (4, "s", 2),
                (3, "d", 10),
                (4, "p", 6),
                (5, "s", 2),
                (4, "d", 10),
                (5, "p", 6),
                (6, "s", 2),
                (4, "f", 14),
                (5, "d", 10),
                (6, "p", 6),
                (7, "s", 2),
                (5, "f", 3),
                (6, "d", 1),
            ],
        }
        for k, v in cases.items():
            assert Element(k).full_electronic_structure == v

        assert Element.Ac.electronic_structure == "[Rn].6d1.7s2"

    def test_group(self):
        cases = {
            "H": 1,
            "He": 18,
            "Li": 1,
            "O": 16,
            "Fe": 8,
            "La": 3,
            "Ce": 3,
            "Lu": 3,
            "U": 3,
            "Lr": 3,
            "Og": 18,
        }
        for k, v in cases.items():
            assert Element(k).group == v

    def test_row(self):
        cases = {
            "H": 1,
            "He": 1,
            "Li": 2,
            "O": 2,
            "Fe": 4,
            "La": 6,
            "Ce": 6,
            "Lu": 6,
            "U": 7,
            "Lr": 7,
            "Og": 7,
        }
        for k, v in cases.items():
            assert Element(k).row == v

    def test_from_name(self):
        cases = {
            "H": "hydrogen",
            "He": "Helium",
            "Li": "lithium",
            "O": "Oxygen",
            "Fe": "Iron",
            "La": "lanthanum",
            "Ce": "Cerium",
            "U": "Uranium",
        }
        for k, v in cases.items():
            assert ElementBase.from_name(v) == Element(k)

    def test_from_row_and_group(self):
        cases = {
            "H": (1, 1),
            "He": (1, 18),
            "Li": (2, 1),
            "O": (2, 16),
            "Fe": (4, 8),
            "La": (8, 3),
            "Ce": (8, 4),
            "Lu": (8, 17),
            "U": (9, 6),
            "Lr": (9, 17),
            "Og": (7, 18),
        }
        for k, v in cases.items():
            assert ElementBase.from_row_and_group(v[0], v[1]) == Element(k)

    def test_n_electrons(self):
        cases = {"O": 8, "Fe": 26, "Li": 3, "Be": 4}
        for k, v in cases.items():
            assert Element(k).n_electrons == v

    def test_valence(self):
        cases = {"O": (1, 4), "Fe": (2, 6), "Li": (0, 1), "Be": (0, 2)}
        for k, v in cases.items():
            assert Element(k).valence == v

        with pytest.raises(ValueError, match="U has ambiguous valence"):
            _ = Element("U").valence

        valence = Element("He").valence
        assert np.isnan(valence[0])
        assert valence[1] == 0

    def test_term_symbols(self):
        cases = {
            "Li": [["2S0.5"]],  # s1
            "C": [["1D2.0"], ["3P0.0", "3P1.0", "3P2.0"], ["1S0.0"]],  # p2
            "Ti": [
                ["1G4.0"],
                ["3F2.0", "3F3.0", "3F4.0"],
                ["1D2.0"],
                ["3P0.0", "3P1.0", "3P2.0"],
                ["1S0.0"],
            ],  # d2
            "Pr": [
                ["2L7.5", "2L8.5"],
                ["2K6.5", "2K7.5"],
                ["4I4.5", "4I5.5", "4I6.5", "4I7.5"],
                ["2I5.5", "2I6.5"],
                ["2H4.5", "2H5.5"],
                ["2H4.5", "2H5.5"],
                ["4G2.5", "4G3.5", "4G4.5", "4G5.5"],
                ["2G3.5", "2G4.5"],
                ["2G3.5", "2G4.5"],
                ["4F1.5", "4F2.5", "4F3.5", "4F4.5"],
                ["2F2.5", "2F3.5"],
                ["2F2.5", "2F3.5"],
                ["4D0.5", "4D1.5", "4D2.5", "4D3.5"],
                ["2D1.5", "2D2.5"],
                ["2D1.5", "2D2.5"],
                ["2P0.5", "2P1.5"],
                ["4S1.5"],
            ],  # f3
            "Ne": [["1S0"]],
        }
        for key, val in cases.items():
            assert Element(key).term_symbols == val

    def test_ground_state_term_symbol(self):
        cases = {
            "Li": "2S0.5",  # s1
            "C": "3P0.0",  # p2
            "O": "3P2.0",  # p4
            "Ti": "3F2.0",  # d2
            "Pr": "4I4.5",
        }  # f3
        for key, val in cases.items():
            assert Element(key).ground_state_term_symbol == val

    def test_attributes(self):
        bool_attrs = {
            ("Xe", "Kr"): ("is_noble_gas", True),
            ("H", "Cl"): ("is_noble_gas", False),
            ("Fe", "Ni"): ("is_transition_metal", True),
            ("Li", "Cs"): ("is_alkali", True),
            ("Ca", "Mg"): ("is_alkaline", True),
            ("F", "Br", "I"): ("is_halogen", True),
            ("La", "Ce", "Lu"): ("is_lanthanoid", True),
            ("U", "Pu"): ("is_actinoid", True),
            ("Si", "Ge"): ("is_metalloid", True),
            ("O", "Te"): ("is_chalcogen", True),
            ("N", "Sb", "Ta"): ("is_chalcogen", False),
            ("Tc", "Po"): ("is_radioactive", True),
            ("H", "Li", "Bi"): ("is_radioactive", False),
        }

        for elements, (attr, expected) in bool_attrs.items():
            for elem in elements:
                assert getattr(Element(elem), attr) is expected, f"{elem=} {attr=}, {expected=}"

        keys = (
            "atomic_mass",
            "atomic_orbitals",
            "atomic_orbitals_eV",
            "atomic_radius",
            "average_anionic_radius",
            "average_cationic_radius",
            "average_ionic_radius",
            "boiling_point",
            "brinell_hardness",
            "bulk_modulus",
            "coefficient_of_linear_thermal_expansion",
            "common_oxidation_states",
            "critical_temperature",
            "density_of_solid",
            "electrical_resistivity",
            "electronic_structure",
            "ground_level",
            "ionic_radii",
            "ionization_energies",
            "iupac_ordering",
            "liquid_range",
            "long_name",
            "max_oxidation_state",
            "melting_point",
            "mendeleev_no",
            "metallic_radius",
            "min_oxidation_state",
            "mineral_hardness",
            "molar_volume",
            "oxidation_states",
            "poissons_ratio",
            "reflectivity",
            "refractive_index",
            "rigidity_modulus",
            "superconduction_temperature",
            "thermal_conductivity",
            "velocity_of_sound",
            "vickers_hardness",
            "youngs_modulus",
        )

        # Test all elements up to Uranium
        for idx in range(1, 104):
            el = Element.from_Z(idx)
            for elements in keys:
                key_str = elements.capitalize().replace("_", " ")
                if key_str in el.data and (el.data[key_str] is not None):
                    assert getattr(el, elements) is not None
                elif elements == "long_name":
                    assert el.long_name == el.data["Name"]
                elif elements == "iupac_ordering":
                    assert "IUPAC ordering" in el.data
                    assert getattr(el, elements) is not None

            if len(el.oxidation_states) > 0:
                assert max(el.oxidation_states) == el.max_oxidation_state
                assert min(el.oxidation_states) == el.min_oxidation_state

            if el.symbol not in {"He", "Ne", "Ar"}:
                assert el.X > 0, f"No electroneg for {el}"

        # Check atomic_orbitals_eV is Ha_to_eV * atomic_orbitals
        for el in Element:
            if el.atomic_orbitals is None:
                continue
            assert el.atomic_orbitals_eV == approx(
                {orb: energy * Ha_to_eV for orb, energy in el.atomic_orbitals.items()}
            )

        with pytest.raises(ValueError, match="Unexpected atomic number Z=1000"):
            Element.from_Z(1000)

    def test_ie_ea(self):
        assert Element.Fe.ionization_energies[2] == approx(30.651)
        assert Element.Fe.ionization_energy == Element.Fe.ionization_energies[0]
        assert Element.Br.electron_affinity == approx(3.3635883)

    def test_oxidation_states(self):
        el = Element.Fe
        assert el.oxidation_states == (-2, -1, 1, 2, 3, 4, 5, 6)
        assert el.common_oxidation_states == (2, 3)
        assert el.icsd_oxidation_states == (2, 3)

    def test_deepcopy(self):
        el1 = Element.Fe
        el2 = Element.Na
        ellist = [el1, el2]
        assert ellist == deepcopy(ellist), "Deepcopy operation doesn't produce exact copy"

    def test_radii(self):
        el = Element.Pd
        assert el.atomic_radius == approx(1.40)
        assert el.atomic_radius_calculated == approx(1.69)
        assert el.van_der_waals_radius == approx(2.10)

    def test_data(self):
        assert Element.Pd.data["Atomic radius"] == approx(1.4)
        al = Element.Al
        val = al.thermal_conductivity
        assert val == 235
        assert str(val.unit) == "W K^-1 m^-1"
        val = al.electrical_resistivity
        assert val == approx(2.7e-08)
        assert str(val.unit) == "m ohm"

    def test_sort(self):
        els = [Element.Se, Element.C]
        assert sorted(els) == [Element.C, Element.Se]

    def test_pickle(self):
        pickled = pickle.dumps(Element.Fe)
        assert Element.Fe == pickle.loads(pickled)  # noqa: S301

        # Test 5 random elements
        rng = np.random.default_rng()
        for idx in rng.integers(1, 104, size=5):
            self.serialize_with_pickle(Element.from_Z(idx))

    def test_print_periodic_table(self):
        Element.print_periodic_table()

    def test_is(self):
        assert Element("Bi").is_post_transition_metal

    def test_isotope(self):
        elems = [Element(el) for el in ("H", "D", "T")]
        assert [x.symbol for x in elems] == ["H", "H", "H"]
        assert list(map(str, elems)) == ["H", "H", "H"]
        assert [el.A for el in elems] == [1, 2, 3]
        assert all(abs(el.atomic_mass - idx - 1) < 0.1 for idx, el in enumerate(elems))
        assert [el.atomic_mass for el in elems] == [
            1.00794,
            2.013553212712,
            3.0155007134,
        ]

        assert Element.named_isotopes == (Element.D, Element.T)


class TestSpecies(MatSciTest):
    def setup_method(self):
        self.specie1 = Species.from_str("Fe2+")
        self.specie2 = Species("Fe", 3)
        self.specie3 = Species("Fe", 2)
        self.specie4 = Species("Fe", 2, spin=5)

    def test_init(self):
        assert Species("Fe", 2) == Species("Fe2+")
        assert Species("Fe", 2, spin=2) == Species("Fe2+", spin=2)
        assert Species("O2-") == Species("O", -2)
        assert Species("O0+", spin=2) == Species("O", 0, spin=2)

    def test_ionic_radius(self):
        assert self.specie2.ionic_radius == approx(78.5 / 100)
        assert self.specie3.ionic_radius == approx(92 / 100)
        assert Species("Mn", 4).ionic_radius == approx(0.67)

    def test_eq(self):
        assert self.specie1 == self.specie3, "Static and actual constructor gives unequal result!"
        assert self.specie1 != self.specie2, "Fe2+ should not be equal to Fe3+"
        assert self.specie4 != self.specie3
        assert self.specie1 != Element("Fe")
        assert Element("Fe") != self.specie1
        assert Element("Fe") == Element("Fe")
        assert Species("Fe", 0) != Element("Fe")
        assert Element("Fe") != Species("Fe", 0)

    def test_cmp(self):
        assert self.specie1 < self.specie2, "Fe2+ should be < Fe3+"
        assert Species("C", 1) < Species("Se", 1)

    def test_attr(self):
        assert self.specie1.Z == 26, "Z attribute for Fe2+ should be = Element Fe."
        assert self.specie4.spin == 5

    def test_deepcopy(self):
        elem_list = [Species("Fe4+"), Species("Na1+")]
        assert elem_list == deepcopy(elem_list), "Deepcopy operation doesn't produce exact copy."

    def test_pickle(self):
        assert self.specie1 == pickle.loads(pickle.dumps(self.specie1))  # noqa: S301
        for idx in range(1, 5):
            self.serialize_with_pickle(getattr(self, f"specie{idx}"))
        cs = Species("Cs1+")
        cl = Species("Cl1+")

        with open(f"{self.tmp_path}/cscl.pickle", "wb") as file:
            pickle.dump((cs, cl), file)

        with open(f"{self.tmp_path}/cscl.pickle", "rb") as file:
            tup = pickle.load(file)  # noqa: S301
            assert tup == (cs, cl)

    def test_get_crystal_field_spin(self):
        assert Species("Fe", 2).get_crystal_field_spin() == 4
        assert Species("Fe", 3).get_crystal_field_spin() == 5
        assert Species("Fe", 4).get_crystal_field_spin() == 4
        assert Species("Co", 3).get_crystal_field_spin(spin_config="low") == 0
        assert Species("Co", 4).get_crystal_field_spin(spin_config="low") == 1
        assert Species("Ni", 3).get_crystal_field_spin(spin_config="low") == 1
        assert Species("Ni", 4).get_crystal_field_spin(spin_config="low") == 0

        for elem in ("Li+", "Ge4+", "H+"):
            symbol = Species(elem).symbol
            with pytest.raises(
                AttributeError,
                match=f"Invalid element {symbol} for crystal field calculation",
            ):
                Species(elem).get_crystal_field_spin()
        with pytest.raises(AttributeError, match="Invalid oxidation state 10 for element Fe"):
            Species("Fe", 10).get_crystal_field_spin()
        with pytest.raises(ValueError, match="Invalid coordination or spin config"):
            Species("Fe", 2).get_crystal_field_spin("hex")

        spin = Species("Co", 3).get_crystal_field_spin("tet", spin_config="low")
        assert spin == 2

    def test_get_nmr_mom(self):
        assert Species("H").get_nmr_quadrupole_moment() == approx(2.860)
        assert Species("Li").get_nmr_quadrupole_moment() == approx(-0.808)
        assert Species("Li").get_nmr_quadrupole_moment("Li-7") == approx(-40.1)
        assert Species("Si").get_nmr_quadrupole_moment() == approx(0)
        with pytest.raises(ValueError, match="No quadrupole moment for isotope='Li-109'"):
            Species("Li").get_nmr_quadrupole_moment("Li-109")

    def test_get_shannon_radius(self):
        assert Species("Li", 1).get_shannon_radius("IV") == approx(0.59)
        mn2 = Species("Mn", 2)
        assert mn2.get_shannon_radius("IV", "High Spin") == approx(0.66)
        assert mn2.get_shannon_radius("V", "High Spin") == approx(0.75)

        with pytest.warns(
            UserWarning,
            match="Specified spin='' not consistent with database spin of High Spin. Only one "
            "spin data available, and that value is returned.",
        ) as warns:
            radius = mn2.get_shannon_radius("V")
            assert len(warns) == 1
            assert radius == approx(0.75)

        assert mn2.get_shannon_radius("VI", "Low Spin") == approx(0.67)
        assert mn2.get_shannon_radius("VI", "High Spin") == approx(0.83)
        assert mn2.get_shannon_radius("VII", "High Spin") == approx(0.9)
        assert mn2.get_shannon_radius("VIII") == approx(0.96)

    def test_sort(self):
        els = map(get_el_sp, ["N3-", "Si4+", "Si3+"])
        assert sorted(els) == [Species("Si", 3), Species("Si", 4), Species("N", -3)]

    def test_to_from_str(self):
        fe3 = Species("Fe", 3, spin=5)
        assert str(fe3) == "Fe3+,spin=5"
        fe = Species.from_str("Fe3+,spin=5")
        assert fe.spin == 5
        mo0 = Species("Mo", 0, spin=5)
        assert str(mo0) == "Mo0+,spin=5"
        mo = Species.from_str("Mo0+,spin=4")
        assert mo.spin == 4

        # Shyue Ping: I don't understand the need for a None for oxidation state. That to me is basically an element.
        # Why make the thing so complicated for a use case that I have never seen???
        # fe_no_ox = Species("Fe", oxidation_state=None, spin=5)
        # fe_no_ox_from_str = Species.from_str("Fe,spin=5")
        # assert fe_no_ox == fe_no_ox_from_str

    def test_no_oxidation_state(self):
        mo0 = Species("Mo", None, spin=5)
        assert str(mo0) == "Mo,spin=5"

    def test_stringify(self):
        assert self.specie2.to_latex_string() == "Fe$^{3+}$"
        assert self.specie2.to_unicode_string() == "Fe³⁺"
        assert Species("S", -2).to_latex_string() == "S$^{2-}$"
        assert Species("S", -2).to_unicode_string() == "S²⁻"


@pytest.mark.parametrize(
    ("symbol_oxi", "expected_element", "expected_oxi_state"),
    [
        ("Fe", "Fe", None),
        ("Fe2+", "Fe", 2),
        ("O2-", "O", -2),
        ("N-", "N", -1),
        ("Ca+", "Ca", 1),
        ("Te3+", "Te", 3),
        ("P5+", "P", 5),
        ("Na0+", "Na", 0),
        ("Na0-", "Na", 0),
        ("C0.53-", "C", -0.53),
        ("Tc3.498+", "Tc", 3.498),
    ],
)
def test_symbol_oxi_state_str(symbol_oxi, expected_element, expected_oxi_state):
    species = Species(symbol_oxi)
    assert species._el.symbol == expected_element
    assert species._oxi_state == approx(expected_oxi_state, rel=1.0e-6)


def test_symbol_oxi_state_str_raises():
    symbol = "Fe2.5f2123+"  # invalid oxidation state
    with pytest.raises(ParseError, match=re.escape(f"Failed to parse {symbol=}")):
        _ = Species(symbol)


class TestDummySpecies:
    def test_init(self):
        self.specie1 = DummySpecies("X")
        with pytest.raises(ValueError, match="Xe contains Xe, which is a valid element symbol"):
            DummySpecies("Xe")
        with pytest.raises(ValueError, match="Xec contains Xe, which is a valid element symbol"):
            DummySpecies("Xec")
        with pytest.raises(ValueError, match="Vac contains V, which is a valid element symbol"):
            DummySpecies("Vac")
        self.specie2 = DummySpecies("X", 2, spin=3)
        assert self.specie2.spin == 3

    def test_attr(self):
        with pytest.raises(AttributeError):
            _ = self.specie2.ionic_radius

    def test_eq(self):
        assert DummySpecies("Xg") != DummySpecies("Xh")
        assert DummySpecies("Xg") != DummySpecies("Xg", 3)
        assert DummySpecies("Xg", 3) == DummySpecies("Xg", 3)

    def test_from_str(self):
        sp = DummySpecies.from_str("X")
        assert sp.oxi_state == 0
        sp = DummySpecies.from_str("X2+")
        assert sp.oxi_state == 2
        assert sp.to_latex_string() == "X$^{2+}$"
        sp = DummySpecies.from_str("X2+spin=5")
        assert sp.oxi_state == 2
        assert sp.spin == 5
        assert sp.to_latex_string() == "X$^{2+}$"
        assert sp.to_html_string() == "X<sup>2+</sup>"
        assert sp.to_unicode_string() == "X²⁺"

    def test_pickle(self):
        el1 = DummySpecies("X", 3)
        pickled = pickle.dumps(el1)
        assert el1 == pickle.loads(pickled)  # noqa: S301

    def test_sort(self):
        Fe, X = Element.Fe, DummySpecies("X")
        assert sorted([Fe, X]) == [X, Fe]
        assert DummySpecies("X", 3) < DummySpecies("X", 4)

        sp = Species("Fe", 2, spin=5)
        with pytest.raises(AttributeError) as exc:
            sp.spin = 6

        # for some reason different message on Windows and Mac. on Linux: 'can't set attribute'
        assert "can't set attribute" in str(exc.value) or "property 'spin' of 'Species' object has no setter" in str(
            exc.value
        )
        assert sp.spin == 5

    def test_species_electronic_structure(self):
        assert Species("Fe", 0).electronic_structure == "[Ar].3d6.4s2"
        assert Species("Fe", 0).n_electrons == 26
        assert Species("Fe", 0).full_electronic_structure == [
            (1, "s", 2),
            (2, "s", 2),
            (2, "p", 6),
            (3, "s", 2),
            (3, "p", 6),
            (4, "s", 2),
            (3, "d", 6),
        ]
        assert Species("Fe", 0).valence == (2, 6)

        assert Species("Fe", 2).electronic_structure == "[Ar].3d6"
        assert Species("Fe", 2).n_electrons == 24
        assert Species("Fe", 2).full_electronic_structure == [
            (1, "s", 2),
            (2, "s", 2),
            (2, "p", 6),
            (3, "s", 2),
            (3, "p", 6),
            (3, "d", 6),
        ]
        assert Species("Fe", 2).valence == (2, 6)

        assert Species("Fe", 3).electronic_structure == "[Ar].3d5"
        assert Species("Fe", 3).n_electrons == 23
        assert Species("Fe", 3).full_electronic_structure == [
            (1, "s", 2),
            (2, "s", 2),
            (2, "p", 6),
            (3, "s", 2),
            (3, "p", 6),
            (3, "d", 5),
        ]
        assert Species("Fe", 3).valence == (2, 5)

        assert Species("Th", 4).electronic_structure == "[Hg].6p6"
        assert Species("Th", 4).full_electronic_structure == [
            (1, "s", 2),
            (2, "s", 2),
            (2, "p", 6),
            (3, "s", 2),
            (3, "p", 6),
            (4, "s", 2),
            (3, "d", 10),
            (4, "p", 6),
            (5, "s", 2),
            (4, "d", 10),
            (5, "p", 6),
            (6, "s", 2),
            (4, "f", 14),
            (5, "d", 10),
            (6, "p", 6),
        ]
        assert Species("Th", 4).valence == (1, 6)

        assert Species("Li", 1).electronic_structure == "1s2"
        assert Species("Li", 1).n_electrons == 2
        # alkali metals, all p
        for el in ["Na", "K", "Rb", "Cs"]:
            assert Species(el, 1).electronic_structure.split(".")[-1][1::] == "p6", f"Failure for {el} +1"
        for el in ["Ca", "Mg", "Ba", "Sr"]:
            assert Species(el, 2).electronic_structure.split(".")[-1][1::] == "p6", f"Failure for {el} +2"
        # valence shell should be f (l=3) for all lanthanide ions except La+3 and Lu+3
        for el in [
            "Ce",
            "Nd",
            "Sm",
            "Eu",
            "Gd",
            "Tb",
            "Dy",
            "Ho",
            "Er",
            "Tm",
            "Yb",
            "Lu",
        ]:
            assert Species(el, 3).valence[0] == 3, f"Failure for {el} +3"

        for el in Element:
            for ox in el.common_oxidation_states:
                if str(el) == "H" and ox == 1:
                    continue
                n_electron_el = sum(orb[-1] for orb in el.full_electronic_structure)
                n_electron_sp = sum(orb[-1] for orb in Species(el.symbol, ox).full_electronic_structure)
                assert n_electron_el - n_electron_sp == ox, f"Failure for {el} {ox}"


def test_get_el_sp():
    assert get_el_sp("Fe2+") == Species("Fe", 2)
    assert get_el_sp("3") == Element.Li
    assert get_el_sp(5) == Element.B
    assert get_el_sp("3.0") == Element.Li
    assert get_el_sp("+3.0") == Element.Li
    assert get_el_sp(2.0) == Element.He
    assert get_el_sp("U") == Element.U
    assert get_el_sp("X2+") == DummySpecies("X", 2)
    assert get_el_sp("Mn3+") == Species("Mn", 3)
    assert get_el_sp("X2+spin=5") == DummySpecies("X", 2, spin=5)

    with pytest.raises(ValueError, match="Can't parse Element or Species from None"):
        get_el_sp(None)


def test_element_type():
    assert isinstance(ElementType.actinoid, Enum)
    assert isinstance(ElementType.metalloid, Enum)
    assert len(ElementType) == 18
