"""This module defines filters for Transmuter object."""

from __future__ import annotations

import abc
import math
from collections import defaultdict
from typing import TYPE_CHECKING

from monty.json import MSONable

from pymatgen.analysis.structure_matcher import ElementComparator, StructureMatcher
from pymatgen.core import get_el_sp
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

if TYPE_CHECKING:
    from typing_extensions import Self

    from pymatgen.core import IStructure, Structure
    from pymatgen.util.typing import SpeciesLike


class AbstractStructureFilter(MSONable, abc.ABC):
    """Structures that return True when passed to the test() method are retained during
    transmutation. Those that return False are removed.
    """

    @abc.abstractmethod
    def test(self, structure: Structure | IStructure):
        """Structures that return true are kept in the Transmuter object during filtering.

        Args:
            structure (Structure): Input structure to test

        Returns:
            bool: True if structure passes filter.
        """


class ContainsSpecieFilter(AbstractStructureFilter):
    """Filter for structures containing certain elements or species.
    By default compares by atomic number.
    """

    def __init__(self, species: SpeciesLike, strict_compare: bool = False, AND: bool = True, exclude: bool = False):
        """
        Args:
            species (list[SpeciesLike]): species to look for
            AND: whether all species must be present to pass (or fail) filter.
            strict_compare: if true, compares objects by specie or element
                object if false, compares atomic number
            exclude: If true, returns false for any structures with the specie
                (excludes them from the Transmuter).
        """
        self._species = list(map(get_el_sp, species))  # type:ignore[arg-type]
        self._strict = strict_compare
        self._AND = AND
        self._exclude = exclude

    def test(self, structure: Structure | IStructure):
        """True if structure does not contain specified species."""
        # set up lists to compare
        if not self._strict:
            # compare by atomic number
            filter_set = {sp.Z for sp in self._species}
            structure_set = {sp.Z for sp in structure.elements}
        else:
            # compare by specie or element object
            filter_set = set(self._species)
            structure_set = set(structure.elements)

        if self._AND and filter_set <= structure_set:
            # return true if we aren't excluding since all are in structure
            return not self._exclude
        if not self._AND and filter_set & structure_set:
            # return true if we aren't excluding since one is in structure
            return not self._exclude
        # return false if we aren't excluding otherwise
        return self._exclude

    def __repr__(self):
        return "\n".join(
            [
                "ContainsSpecieFilter with parameters:",
                f"species = {self._species}",
                f"strict_compare = {self._strict}",
                f"AND = {self._AND}",
                f"exclude = {self._exclude}",
            ]
        )

    def as_dict(self) -> dict:
        """Get MSONable dict."""
        return {
            "@module": type(self).__module__,
            "@class": type(self).__name__,
            "init_args": {
                "species": [str(sp) for sp in self._species],
                "strict_compare": self._strict,
                "AND": self._AND,
                "exclude": self._exclude,
            },
        }

    @classmethod
    def from_dict(cls, dct: dict) -> Self:
        """
        Args:
            dct (dict): Dict representation.

        Returns:
            Filter
        """
        return cls(**dct["init_args"])


class SpecieProximityFilter(AbstractStructureFilter):
    """This filter removes structures that have certain species that are too close together."""

    def __init__(self, specie_and_min_dist_dict):
        """
        Args:
            specie_and_min_dist_dict (dict): A species string to float mapping. For
                example, {"Na+": 1} means that all Na+ ions must be at least 1
                Angstrom away from each other. Multiple species criteria can be
                applied. Note that the testing is done based on the actual object
                . If you have a structure with Element, you must use {"Na":1}
                instead to filter based on Element and not Species.
        """
        self.specie_and_min_dist = {get_el_sp(k): v for k, v in specie_and_min_dist_dict.items()}

    def test(self, structure: Structure):
        """True if structure does not contain species within specified distances."""
        all_species = set(self.specie_and_min_dist)
        for site in structure:
            species = set(site.species)
            if sp_to_test := species.intersection(all_species):
                max_r = max(self.specie_and_min_dist[sp] for sp in sp_to_test)
                neighbors = structure.get_neighbors(site, max_r)
                for sp in sp_to_test:
                    for nn_site, dist, *_ in neighbors:
                        if sp in nn_site.species and dist < self.specie_and_min_dist[sp]:
                            return False
        return True

    def as_dict(self):
        """Get MSONable dict."""
        return {
            "@module": type(self).__module__,
            "@class": type(self).__name__,
            "init_args": {"specie_and_min_dist_dict": {str(sp): v for sp, v in self.specie_and_min_dist.items()}},
        }

    @classmethod
    def from_dict(cls, dct: dict) -> Self:
        """
        Args:
            dct (dict): Dict representation.

        Returns:
            SpecieProximityFilter
        """
        return cls(**dct["init_args"])


class RemoveDuplicatesFilter(AbstractStructureFilter):
    """This filter removes exact duplicate structures from the transmuter."""

    def __init__(
        self,
        structure_matcher: dict | StructureMatcher | None = None,
        symprec: float | None = None,
    ) -> None:
        """Remove duplicate structures based on the structure matcher
        and symmetry (if symprec is given).

        Args:
            structure_matcher (dict | StructureMatcher, optional): Provides a structure matcher to be used for
                structure comparison.
            symprec (float, optional): The precision in the symmetry finder algorithm if None (
                default value), no symmetry check is performed and only the
                structure matcher is used. A recommended value is 1e-5.
        """
        self.symprec = symprec
        self.structure_list: dict[str, list[Structure]] = defaultdict(list)
        if not isinstance(structure_matcher, dict | StructureMatcher | type(None)):
            raise TypeError(f"{structure_matcher=} must be a dict, StructureMatcher or None")
        if isinstance(structure_matcher, dict):
            self.structure_matcher = StructureMatcher.from_dict(structure_matcher)
        else:
            self.structure_matcher = structure_matcher or StructureMatcher(comparator=ElementComparator())

    def test(self, structure: Structure) -> bool:
        """
        Args:
            structure (Structure): Input structure to test.

        Returns:
            bool: True if structure is not in list.
        """
        hash_comp = self.structure_matcher._comparator.get_hash(structure.composition)
        if not self.structure_list[hash_comp]:
            self.structure_list[hash_comp].append(structure)
            return True

        def get_spg_num(struct: Structure) -> int:
            finder = SpacegroupAnalyzer(struct, symprec=self.symprec)  # type:ignore[arg-type]
            return finder.get_space_group_number()

        for struct in self.structure_list[hash_comp]:
            if (self.symprec is None or get_spg_num(struct) == get_spg_num(structure)) and self.structure_matcher.fit(
                struct, structure
            ):
                return False

        self.structure_list[hash_comp].append(structure)
        return True


class RemoveExistingFilter(AbstractStructureFilter):
    """This filter removes structures existing in a given list from the transmuter."""

    def __init__(
        self,
        existing_structures: list[Structure],
        structure_matcher: dict | StructureMatcher | None = None,
        symprec: float | None = None,
    ) -> None:
        """Remove existing structures based on the structure matcher
        and symmetry (if symprec is given).

        Args:
            existing_structures (list[Structure]): Existing structures to compare with.
            structure_matcher (dict | StructureMatcher, optional): Will be used for
                structure comparison.
            symprec (float | None): The precision in the symmetry finder algorithm.
                If None (default value), no symmetry check is performed and only the
                structure matcher is used. A recommended value is 1e-5.
        """
        self.symprec = symprec
        self.structure_list: list = []
        self.existing_structures = existing_structures
        if isinstance(structure_matcher, dict):
            self.structure_matcher = StructureMatcher.from_dict(structure_matcher)
        else:
            self.structure_matcher = structure_matcher or StructureMatcher(comparator=ElementComparator())

    def test(self, structure: Structure):
        """True if structure is not in existing list."""

        def get_sg(s):
            finder = SpacegroupAnalyzer(s, symprec=self.symprec)
            return finder.get_space_group_number()

        for struct in self.existing_structures:
            if (
                (
                    self.structure_matcher._comparator.get_hash(structure.composition)
                    == self.structure_matcher._comparator.get_hash(struct.composition)
                    and self.symprec is None
                )
                or get_sg(struct) == get_sg(structure)
            ) and self.structure_matcher.fit(struct, structure):
                return False

        self.structure_list.append(structure)
        return True

    def as_dict(self):
        """Get MSONable dict."""
        return {
            "@module": type(self).__module__,
            "@class": type(self).__name__,
            "init_args": {"structure_matcher": self.structure_matcher.as_dict()},
        }


class ChargeBalanceFilter(AbstractStructureFilter):
    """This filter removes structures that are not charge balanced from the
    transmuter. This only works if the structure is oxidation state
    decorated, as structures with only elemental sites are automatically
    assumed to have net charge of 0.
    """

    def __init__(self):
        """No args required."""

    def test(self, structure: Structure):
        """True if structure is neutral."""
        return math.isclose(structure.charge, 0.0)


class SpeciesMaxDistFilter(AbstractStructureFilter):
    """This filter removes structures that do have two particular species that are
    not nearest neighbors by a predefined max_dist. For instance, if you are
    analyzing Li battery materials, you would expect that each Li+ would be
    nearest neighbor to lower oxidation state transition metal for
    electrostatic reasons. This only works if the structure is oxidation state
    decorated, as structures with only elemental sites are automatically
    assumed to have net charge of 0.
    """

    def __init__(self, sp1, sp2, max_dist):
        """
        Args:
            sp1 (Species): First specie
            sp2 (Species): Second specie
            max_dist (float): Maximum distance between species.
        """
        self.sp1 = get_el_sp(sp1)
        self.sp2 = get_el_sp(sp2)
        self.max_dist = max_dist

    def test(self, structure: Structure):
        """True if structure contains the two species but their distance is greater than max_dist."""
        sp1_indices = [idx for idx, site in enumerate(structure) if site.specie == self.sp1]
        sp2_indices = [idx for idx, site in enumerate(structure) if site.specie == self.sp2]
        frac_coords1 = structure.frac_coords[sp1_indices, :]
        frac_coords2 = structure.frac_coords[sp2_indices, :]
        lattice = structure.lattice
        dists = lattice.get_all_distances(frac_coords1, frac_coords2)
        return all(any(row) for row in dists < self.max_dist)
