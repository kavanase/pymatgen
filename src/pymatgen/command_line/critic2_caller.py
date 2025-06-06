"""This module implements an interface to the critic2 Bader analysis code.

For most Bader analysis purposes, users are referred to
pymatgen.command_line.bader_caller instead, this module is for advanced
usage requiring identification of critical points in the charge density.

This module depends on a compiled critic2 executable available in the path.
Please follow the instructions at https://github.com/aoterodelaroza/critic2
to compile.

New users are *strongly* encouraged to read the critic2 manual first.

In brief,
* critic2 searches for critical points in charge density
* a critical point can be one of four types: nucleus, bond, ring
or cage
* it does this by seeding locations for likely critical points
and then searching in these regions
* there are two lists of critical points in the output, a list
of non-equivalent points (with in-depth information about the
field at those points), and a full list of points generated
by the appropriate symmetry operations
* connectivity between these points is also provided when
appropriate (e.g. the two nucleus critical points linked to
 a bond critical point)
* critic2 can do many other things besides

If you use this module, please cite:

A. Otero-de-la-Roza, E. R. Johnson and V. Luaña,
Comput. Phys. Communications 185, 1007-1018 (2014)
(https://doi.org/10.1016/j.cpc.2013.10.026)

A. Otero-de-la-Roza, M. A. Blanco, A. Martín Pendás and
V. Luaña, Comput. Phys. Communications 180, 157-166 (2009)
(https://doi.org/10.1016/j.cpc.2008.07.018)
"""

from __future__ import annotations

import logging
import os
import subprocess
import warnings
from enum import Enum, unique
from glob import glob
from shutil import which
from typing import TYPE_CHECKING

import numpy as np
from monty.dev import requires
from monty.json import MSONable
from monty.serialization import loadfn
from monty.tempfile import ScratchDir
from scipy.spatial import KDTree

from pymatgen.analysis.graphs import StructureGraph
from pymatgen.core import DummySpecies
from pymatgen.io.vasp.inputs import Potcar
from pymatgen.io.vasp.outputs import Chgcar, VolumetricData
from pymatgen.util.due import Doi, due

if TYPE_CHECKING:
    from typing_extensions import Self

    from pymatgen.core import Structure

logger = logging.getLogger(__name__)

due.cite(
    Doi("10.1016/j.cpc.2008.07.018"),
    description="Critic: a new program for the topological analysis of solid-state electron densities",
)
due.cite(
    Doi("10.1016/j.cpc.2013.10.026"),
    description="Critic2: A program for real-space analysis of quantum chemical interactions in solids",
)


class Critic2Caller:
    """Call critic2 and store standard output for further processing."""

    @requires(
        which("critic2"),  # type: ignore[arg-type]
        "Critic2Caller requires the executable critic to be in the path. "
        "Please follow the instructions at https://github.com/aoterodelaroza/critic2.",
    )
    def __init__(self, input_script: str):
        """Run Critic2 on a given input script.

        Args:
            input_script: string defining the critic2 input
        """
        # store if examining the input script is useful,
        # not otherwise used
        self._input_script = input_script

        with open("input_script.cri", mode="w", encoding="utf-8") as file:
            file.write(input_script)

        args = ["critic2", "input_script.cri"]
        with subprocess.Popen(args, stdout=subprocess.PIPE, stdin=subprocess.PIPE, close_fds=True) as rs:
            _stdout, _stderr = rs.communicate()
        stdout = _stdout.decode()

        stderr = ""
        if _stderr:
            stderr = _stderr.decode()
            warnings.warn(stderr, stacklevel=2)

        if rs.returncode != 0:
            raise RuntimeError(f"critic2 exited with return code {rs.returncode}: {stdout}")

        self._stdout = stdout
        self._stderr = stderr

        cp_report = loadfn("cpreport.json") if os.path.isfile("cpreport.json") else None
        self._cp_report = cp_report

        yt = loadfn("yt.json") if os.path.isfile("yt.json") else None
        self._yt = yt

    @classmethod
    def from_chgcar(
        cls,
        structure,
        chgcar=None,
        chgcar_ref=None,
        user_input_settings=None,
        write_cml=False,
        write_json=True,
        zpsp=None,
    ) -> Self:
        """Run Critic2 in automatic mode on a supplied structure, charge
        density (chgcar) and reference charge density (chgcar_ref).

        The reason for a separate reference field is that in
        VASP, the CHGCAR charge density only contains valence
        electrons and may be missing substantial charge at
        nuclei leading to misleading results. Thus, a reference
        field is commonly constructed from the sum of AECCAR0
        and AECCAR2 which is the total charge density, but then
        the valence charge density is used for the final analysis.

        If chgcar_ref is not supplied, chgcar will be used as the
        reference field. If chgcar is not supplied, the promolecular
        charge density will be used as the reference field -- this can
        often still give useful results if only topological information
        is wanted.

        User settings is a dictionary that can contain:
        * GRADEPS, float (field units), gradient norm threshold
        * CPEPS, float (Bohr units in crystals), minimum distance between
          critical points for them to be equivalent
        * NUCEPS, same as CPEPS but specifically for nucleus critical
          points (critic2 default is dependent on grid dimensions)
        * NUCEPSH, same as NUCEPS but specifically for hydrogen nuclei
          since associated charge density can be significantly displaced
          from hydrogen nucleus
        * EPSDEGEN, float (field units), discard critical point if any
          element of the diagonal of the Hessian is below this value,
          useful for discarding points in vacuum regions
        * DISCARD, float (field units), discard critical points with field
          value below this value, useful for discarding points in vacuum
          regions
        * SEED, list of strings, strategies for seeding points, default
          is ['WS 1', 'PAIR 10'] which seeds critical points by
          sub-dividing the Wigner-Seitz cell and between every atom pair
          closer than 10 Bohr, see critic2 manual for more options

        Args:
            structure: Structure to analyze
            chgcar: Charge density to use for analysis. If None, will
                use promolecular density. Should be a Chgcar object or path (string).
            chgcar_ref: Reference charge density. If None, will use
                chgcar as reference. Should be a Chgcar object or path (string).
            user_input_settings (dict): as explained above
            write_cml (bool): Useful for debug, if True will write all
                critical points to a file 'table.cml' in the working directory
                useful for visualization
            write_json (bool): Whether to write out critical points
                and YT JSON. YT integration will be performed with this setting.
            zpsp (dict): Dict of element/symbol name to number of electrons
                (ZVAL in VASP pseudopotential), with which to properly augment core regions
                and calculate charge transfer. Optional.
        """
        settings = {"CPEPS": 0.1, "SEED": ["WS", "PAIR DIST 10"]}
        if user_input_settings:
            settings.update(user_input_settings)

        # Load crystal structure
        input_script = ["crystal POSCAR"]

        # Load data to use as reference field
        if chgcar_ref:
            input_script += ["load ref.CHGCAR id chg_ref", "reference chg_ref"]

        # Load data to use for analysis
        if chgcar:
            input_script += ["load int.CHGCAR id chg_int", "integrable chg_int"]
            if zpsp:
                zpsp_str = f" zpsp {' '.join(f'{symbol} {int(zval)}' for symbol, zval in zpsp.items())}"
                input_script[-2] += zpsp_str

        # Command to run automatic analysis
        auto = "auto "
        for k, v in settings.items():
            if isinstance(v, list):
                for item in v:
                    auto += f"{k} {item} "
            else:
                auto += f"{k} {v} "
        input_script += [auto]

        if write_cml:
            input_script += ["cpreport ../table.cml cell border graph"]

        if write_json:
            input_script += ["cpreport cpreport.json"]

        if write_json and chgcar:
            # requires gridded data to work
            input_script += ["yt"]
            input_script += ["yt JSON yt.json"]

        input_script_str = "\n".join(input_script)

        with ScratchDir("."):
            structure.to(filename="POSCAR")

            if chgcar and isinstance(chgcar, VolumetricData):
                chgcar.write_file("int.CHGCAR")
            elif chgcar:
                os.symlink(chgcar, "int.CHGCAR")

            if chgcar_ref and isinstance(chgcar_ref, VolumetricData):
                chgcar_ref.write_file("ref.CHGCAR")
            elif chgcar_ref:
                os.symlink(chgcar_ref, "ref.CHGCAR")

            caller = cls(input_script_str)

            caller.output = Critic2Analysis(
                structure,
                stdout=caller._stdout,
                stderr=caller._stderr,
                cpreport=caller._cp_report,
                yt=caller._yt,
                zpsp=zpsp,
            )

            return caller

    @classmethod
    def from_path(cls, path, suffix="", zpsp=None) -> Self:
        """Convenience method to run critic2 analysis on a folder with typical VASP output files.

        This method will:

        1. Look for files CHGCAR, AECAR0, AECAR2, POTCAR or their gzipped
        counterparts.

        2. If AECCAR* files are present, constructs a temporary reference
        file as AECCAR0 + AECCAR2.

        3. Runs critic2 analysis twice: once for charge, and a second time
        for the charge difference (magnetization density).

        Args:
            path: path to folder to search in
            suffix: specific suffix to look for (e.g. '.relax1' for
                'CHGCAR.relax1.gz')
            zpsp: manually specify ZPSP if POTCAR not present
        """
        chgcar_path = get_filepath("CHGCAR", "Could not find CHGCAR!", path, suffix)
        chgcar = Chgcar.from_file(chgcar_path)
        chgcar_ref = None

        if not zpsp and (
            potcar_path := get_filepath(
                "POTCAR",
                "Could not find POTCAR, will not be able to calculate charge transfer.",
                path,
                suffix,
            )
        ):
            potcar = Potcar.from_file(potcar_path)
            zpsp = {p.element: p.zval for p in potcar}

        if not zpsp:
            # try and get reference "all-electron-like" charge density if zpsp not present
            aeccar0_path = get_filepath(
                "AECCAR0",
                "Could not find AECCAR0, interpret Bader results with caution.",
                path,
                suffix,
            )
            aeccar0 = Chgcar.from_file(aeccar0_path) if aeccar0_path else None

            aeccar2_path = get_filepath(
                "AECCAR2",
                "Could not find AECCAR2, interpret Bader results with caution.",
                path,
                suffix,
            )
            aeccar2 = Chgcar.from_file(aeccar2_path) if aeccar2_path else None

            chgcar_ref = aeccar0.linear_add(aeccar2) if (aeccar0 and aeccar2) else None

        return cls.from_chgcar(chgcar.structure, chgcar, chgcar_ref, zpsp=zpsp)


@unique
class CriticalPointType(Enum):
    """Enum type for the different varieties of critical point."""

    nucleus = "nucleus"  # (3, -3)
    bond = "bond"  # (3, -1)
    ring = "ring"  # (3, 1)
    cage = "cage"  # (3, 3)
    nnattr = "nnattr"  # (3, -3), non-nuclear attractor


def get_filepath(filename, warning, path, suffix):
    """
    Args:
        filename: Filename
        warning: Warning message
        path: Path to search
        suffix: Suffixes to search.
    """
    paths = glob(os.path.join(path, f"{filename}{suffix}*"))
    if not paths:
        warnings.warn(warning, stacklevel=2)
        return None
    if len(paths) > 1:
        # using reverse=True because, if multiple files are present,
        # they likely have suffixes 'static', 'relax', 'relax2', etc.
        # and this would give 'static' over 'relax2' over 'relax'
        # however, better to use 'suffix' kwarg to avoid this!
        paths.sort(reverse=True)
        warnings.warn(f"Multiple files detected, using {os.path.basename(path)}", stacklevel=2)
    return paths[0]


class CriticalPoint(MSONable):
    """Access information about a critical point and the field values at that point."""

    def __init__(
        self,
        index,
        type,  # noqa: A002
        frac_coords,
        point_group,
        multiplicity,
        field,
        field_gradient,
        coords=None,
        field_hessian=None,
    ):
        """Characterize a critical point from a topological
        analysis of electron charge density.

        Note this class is usually associated with a Structure, so
        has information on multiplicity/point group symmetry.

        Args:
            index: index of point
            type: type of point, given as a string
            coords: Cartesian coordinates in Angstroms
            frac_coords: fractional coordinates
            point_group: point group associated with critical point
            multiplicity: number of equivalent critical points
            field: value of field at point (f)
            field_gradient: gradient of field at point (grad f)
            field_hessian: hessian of field at point (del^2 f)
        """
        self.index = index
        self._type = type
        self.coords = coords
        self.frac_coords = frac_coords
        self.point_group = point_group
        self.multiplicity = multiplicity
        self.field = field
        self.field_gradient = field_gradient
        self.field_hessian = field_hessian

    @property
    def type(self) -> CriticalPointType:
        """Instance of CriticalPointType."""
        return CriticalPointType(self._type)

    def __str__(self):
        return f"Critical Point: {self.type.name} ({self.frac_coords})"

    @property
    def laplacian(self) -> float:
        """The Laplacian of the field at the critical point."""
        return np.trace(self.field_hessian)

    @property
    def ellipticity(self):
        """Most meaningful for bond critical points, can be physically interpreted as e.g.
        degree of pi-bonding in organic molecules. Consult literature for more info.

        Returns:
            float: The ellipticity of the field at the critical point.
        """
        eig, _ = np.linalg.eig(self.field_hessian)
        eig.sort()
        return eig[0] / eig[1] - 1


class Critic2Analysis(MSONable):
    """Process the standard output from critic2 into pymatgen-compatible objects."""

    def __init__(
        self,
        structure: Structure,
        stdout: str | None = None,
        stderr: str | None = None,
        cpreport: dict | None = None,
        yt: dict | None = None,
        zpsp: dict | None = None,
    ) -> None:
        """This class is used to store results from the Critic2Caller.

        To explore the bond graph, use the "structure_graph"
        method, which returns a user-friendly StructureGraph
        class with bonding information. By default, this returns
        a StructureGraph with edge weights as bond lengths, but
        can optionally return a graph with edge weights as any
        property supported by the `CriticalPoint` class, such as
        bond ellipticity.

        This class also provides an interface to explore just the
        non-symmetrically-equivalent critical points via the
        `critical_points` attribute, and also all critical
        points (via nodes dict) and connections between them
        (via edges dict). The user should be familiar with critic2
        before trying to understand these.

        Indexes of nucleus critical points in the nodes dict are the
        same as the corresponding sites in structure, with indices of
        other critical points arbitrarily assigned.

        Only one of (stdout, cpreport) required, with cpreport preferred
        since this is a new, native JSON output from critic2.

        Args:
            structure: associated Structure
            stdout: stdout from running critic2 in automatic mode
            stderr: stderr from running critic2 in automatic mode
            cpreport: JSON output from CPREPORT command
            yt: JSON output from YT command
            zpsp (dict): Dict of element/symbol name to number of electrons
                (ZVAL in VASP pseudopotential), with which to calculate charge transfer.
                Optional.

        Args:
            structure (Structure): Associated Structure.
            stdout (str, optional): stdout from running critic2 in automatic mode.
            stderr (str, optional): stderr from running critic2 in automatic mode.
            cpreport (dict, optional): JSON output from CPREPORT command. Either this or stdout required.
            yt (dict, optional): JSON output from YT command.
            zpsp (dict, optional): Dict of element/symbol name to number of electrons (ZVAL in VASP pseudopotential),
                with which to calculate charge transfer. Optional.

        Raises:
            ValueError: If one of cpreport or stdout is not provided.
        """
        self.structure = structure

        self._stdout = stdout
        self._stderr = stderr
        self._cpreport = cpreport
        self._yt = yt
        self._zpsp = zpsp

        self.nodes: dict[int, dict] = {}
        self.edges: dict[int, dict] = {}

        if yt:
            self.structure = self._annotate_structure_with_yt(yt, structure, zpsp)

        if cpreport:
            self._parse_cpreport(cpreport)
        elif stdout:
            self._parse_stdout(stdout)
        else:
            raise ValueError("One of cpreport or stdout required.")

        self._remap_indices()

    def structure_graph(self, include_critical_points=("bond", "ring", "cage")):
        """A StructureGraph object describing bonding information in the crystal.

        Args:
            include_critical_points: add DummySpecies for the critical points themselves, a list of
                "nucleus", "bond", "ring", "cage", set to None to disable

        Returns:
            StructureGraph
        """
        structure = self.structure.copy()

        point_idx_to_struct_idx = {}
        if include_critical_points:
            # atoms themselves don't have field information
            # so set to 0
            for prop in ("ellipticity", "laplacian", "field"):
                structure.add_site_property(prop, [0] * len(structure))
            for idx, node in self.nodes.items():
                cp = self.critical_points[node["unique_idx"]]
                if cp.type.value in include_critical_points:
                    specie = DummySpecies(f"X{cp.type.value[0]}cp", oxidation_state=None)
                    structure.append(
                        specie,
                        node["frac_coords"],
                        properties={
                            "ellipticity": cp.ellipticity,
                            "laplacian": cp.laplacian,
                            "field": cp.field,
                        },
                    )
                    point_idx_to_struct_idx[idx] = len(structure) - 1

        edge_weight = "bond_length"
        edge_weight_units = "Å"

        struct_graph = StructureGraph.from_empty_graph(
            structure,
            name="bonds",
            edge_weight_name=edge_weight,
            edge_weight_units=edge_weight_units,
        )

        edges = self.edges.copy()
        idx_to_delete = []
        # check for duplicate bonds
        for idx, edge in edges.items():
            unique_idx = self.nodes[idx]["unique_idx"]
            # only check edges representing bonds, not rings
            if self.critical_points[unique_idx].type == CriticalPointType.bond and idx not in idx_to_delete:
                for idx2, edge2 in edges.items():
                    if idx != idx2 and edge == edge2:
                        idx_to_delete.append(idx2)
                        warnings.warn(
                            "Duplicate edge detected, try re-running "
                            "critic2 with custom parameters to fix this. "
                            "Mostly harmless unless user is also "
                            "interested in rings/cages.",
                            stacklevel=2,
                        )
                        logger.debug(
                            f"Duplicate edge between points {idx} (unique point {self.nodes[idx]['unique_idx']})"
                            f"and {idx2} ({self.nodes[idx2]['unique_idx']})."
                        )
        # and remove any duplicate bonds present
        for idx in idx_to_delete:
            del edges[idx]

        for idx, edge in edges.items():
            unique_idx = self.nodes[idx]["unique_idx"]
            # only add edges representing bonds, not rings
            if self.critical_points[unique_idx].type == CriticalPointType.bond:
                from_idx = edge["from_idx"]
                to_idx = edge["to_idx"]

                # have to also check bond is between nuclei if non-nuclear
                # attractors not in structure
                skip_bond = False
                if include_critical_points and "nnattr" not in include_critical_points:
                    from_type = self.critical_points[self.nodes[from_idx]["unique_idx"]].type
                    to_type = self.critical_points[self.nodes[from_idx]["unique_idx"]].type
                    skip_bond = (from_type != CriticalPointType.nucleus) or (to_type != CriticalPointType.nucleus)

                if not skip_bond:
                    from_lvec = edge["from_lvec"]
                    to_lvec = edge["to_lvec"]

                    relative_lvec = np.subtract(to_lvec, from_lvec)

                    # for edge case of including nnattrs in bonding graph when other critical
                    # points also included, indices may get mixed
                    struct_from_idx = point_idx_to_struct_idx.get(from_idx, from_idx)
                    struct_to_idx = point_idx_to_struct_idx.get(to_idx, to_idx)

                    weight = self.structure.get_distance(struct_from_idx, struct_to_idx, jimage=relative_lvec)

                    crit_point = self.critical_points[unique_idx]

                    edge_properties = {
                        "field": crit_point.field,
                        "laplacian": crit_point.laplacian,
                        "ellipticity": crit_point.ellipticity,
                        "frac_coords": self.nodes[idx]["frac_coords"],
                    }

                    struct_graph.add_edge(
                        struct_from_idx,
                        struct_to_idx,
                        from_jimage=from_lvec,
                        to_jimage=to_lvec,
                        weight=weight,
                        edge_properties=edge_properties,
                    )

        return struct_graph

    def get_critical_point_for_site(self, n: int):
        """
        Args:
            n (int): Site index.

        Returns:
            CriticalPoint
        """
        return self.critical_points[self.nodes[n]["unique_idx"]]

    def get_volume_and_charge_for_site(self, idx):
        """
        Args:
            idx: Site index.

        Returns:
            dict: with "volume" and "charge" keys, or None if YT integration not performed
        """
        if not self._node_values:
            return None
        return self._node_values[idx]

    def _parse_cpreport(self, cpreport):
        def get_type(signature: int, is_nucleus: bool):
            if signature == 3:
                return "cage"
            if signature == 1:
                return "ring"
            if signature == -1:
                return "bond"
            if signature == -3:
                if is_nucleus:
                    return "nucleus"
                return "nnattr"
            return None

        bohr_to_angstrom = 0.529177

        self.critical_points = [
            CriticalPoint(
                p["id"] - 1,
                get_type(p["signature"], p["is_nucleus"]),
                p["fractional_coordinates"],
                p["point_group"],
                p["multiplicity"],
                p["field"],
                p["gradient"],
                coords=(
                    [x * bohr_to_angstrom for x in p["cartesian_coordinates"]] if cpreport["units"] == "bohr" else None
                ),
                field_hessian=p["hessian"],
            )
            for p in cpreport["critical_points"]["nonequivalent_cps"]
        ]

        for point in cpreport["critical_points"]["cell_cps"]:
            self._add_node(
                idx=point["id"] - 1,
                unique_idx=point["nonequivalent_id"] - 1,
                frac_coords=point["fractional_coordinates"],
            )
            if "attractors" in point:
                self._add_edge(
                    idx=point["id"] - 1,
                    from_idx=int(point["attractors"][0]["cell_id"]) - 1,
                    from_lvec=point["attractors"][0]["lvec"],
                    to_idx=int(point["attractors"][1]["cell_id"]) - 1,
                    to_lvec=point["attractors"][1]["lvec"],
                )

    def _remap_indices(self):
        """Re-maps indices on self.nodes and self.edges such that node indices match
        that of structure, and then sorts self.nodes by index.
        """
        # Order of nuclei provided by critic2 doesn't
        # necessarily match order of sites in Structure.
        # This is because critic2 performs a symmetrization step.
        # We perform a mapping from one to the other,
        # and re-index all nodes accordingly.
        node_mapping = {}  # critic2_index:structure_index
        # ensure frac coords are in [0,1] range
        frac_coords = np.array(self.structure.frac_coords) % 1
        kd = KDTree(frac_coords)

        node_mapping = {}
        for idx, node in self.nodes.items():
            if self.critical_points[node["unique_idx"]].type == CriticalPointType.nucleus:
                node_mapping[idx] = kd.query(node["frac_coords"])[1]

        if len(node_mapping) != len(self.structure):
            warnings.warn(
                f"Check that all sites in input structure ({len(self.structure)}) have "
                f"been detected by critic2 ({len(node_mapping)}).",
                stacklevel=2,
            )

        self.nodes = {node_mapping.get(idx, idx): node for idx, node in self.nodes.items()}

        for edge in self.edges.values():
            edge["from_idx"] = node_mapping.get(edge["from_idx"], edge["from_idx"])
            edge["to_idx"] = node_mapping.get(edge["to_idx"], edge["to_idx"])

    @staticmethod
    def _annotate_structure_with_yt(yt, structure: Structure, zpsp):
        volume_idx = charge_idx = None

        for prop in yt["integration"]["properties"]:
            if prop["label"] == "Volume":
                volume_idx = prop["id"] - 1  # 1-indexed, change to 0
            elif prop["label"] == "$chg_int":
                charge_idx = prop["id"] - 1

        def get_volume_and_charge(nonequiv_idx):
            attractor = yt["integration"]["attractors"][nonequiv_idx - 1]
            if attractor["id"] != nonequiv_idx:
                raise ValueError(f"List of attractors may be un-ordered (wanted id={nonequiv_idx}): {attractor}")
            return (
                attractor["integrals"][volume_idx],
                attractor["integrals"][charge_idx],
            )

        volumes = []
        charges = []
        charge_transfer = []

        for idx, site in enumerate(yt["structure"]["cell_atoms"]):
            if not np.allclose(structure[idx].frac_coords, site["fractional_coordinates"]):
                raise IndexError(
                    f"Site in structure doesn't seem to match site in YT integration:\n{structure[idx]}\n{site}"
                )
            volume, charge = get_volume_and_charge(site["nonequivalent_id"])
            volumes.append(volume)
            charges.append(charge)
            if zpsp:
                if structure[idx].species_string in zpsp:
                    charge_transfer.append(charge - zpsp[structure[idx].species_string])
                else:
                    raise ValueError(
                        f"ZPSP argument does not seem compatible with species in structure "
                        f"({structure[idx].species_string}): {zpsp}"
                    )

        structure = structure.copy()
        structure.add_site_property("bader_volume", volumes)
        structure.add_site_property("bader_charge", charges)

        if zpsp:
            if len(charge_transfer) != len(charges):
                warnings.warn(f"Something went wrong calculating charge transfer: {charge_transfer}", stacklevel=2)
            else:
                structure.add_site_property("bader_charge_transfer", charge_transfer)

        return structure

    def _parse_stdout(self, stdout):
        warnings.warn(
            "Parsing critic2 standard output is deprecated and will not be maintained, "
            "please use the native JSON output in the future.",
            DeprecationWarning,
            stacklevel=2,
        )

        stdout = stdout.split("\n")

        # NOTE WE ARE USING 0-BASED INDEXING:
        # This is different from critic2 which
        # uses 1-based indexing, so all parsed
        # indices have 1 subtracted.

        # Parsing happens in two stages:

        # 1. We construct a list of unique critical points
        #    (i.e. non-equivalent by the symmetry of the crystal)
        #   and the properties of the field at those points

        # 2. We construct a list of nodes and edges describing
        #    all critical points in the crystal

        # Steps 1. and 2. are essentially independent, except
        # that the critical points in 2. have a pointer to their
        # associated unique critical point in 1. so that more
        # information on that point can be retrieved if necessary.

        unique_critical_points = []

        # parse unique critical points
        start_i = end_i = unique_idx = None
        for idx, line in enumerate(stdout):
            if "mult  name            f             |grad|           lap" in line:
                start_i = idx + 1
            elif "* Analysis of system bonds" in line:
                end_i = idx - 2
        # if start_i and end_i haven't been found, we
        # need to re-evaluate assumptions in this parser!

        for idx, line in enumerate(stdout):
            if start_i <= idx <= end_i:
                split = line.replace("(", "").replace(")", "").split()

                unique_idx = int(split[0]) - 1
                point_group = split[1]
                # type = l[2]  # type from definition of critical point e.g. (3, -3)
                critical_point_type = split[3]  # type from name, e.g. nucleus
                frac_coords = [float(split[4]), float(split[5]), float(split[6])]
                multiplicity = float(split[7])
                # name = float(l[8])
                field = float(split[9])
                field_gradient = float(split[10])
                # laplacian = float(l[11])

                point = CriticalPoint(
                    unique_idx,
                    critical_point_type,
                    frac_coords,
                    point_group,
                    multiplicity,
                    field,
                    field_gradient,
                )
                unique_critical_points.append(point)

        for idx, line in enumerate(stdout):
            if "+ Critical point no." in line:
                unique_idx = int(line.split()[4]) - 1
            elif "Hessian:" in line:
                l1 = list(map(float, stdout[idx + 1].split()))
                l2 = list(map(float, stdout[idx + 2].split()))
                l3 = list(map(float, stdout[idx + 3].split()))
                hessian = [
                    [l1[0], l1[1], l1[2]],
                    [l2[0], l2[1], l2[2]],
                    [l3[0], l3[1], l3[2]],
                ]
                unique_critical_points[unique_idx].field_hessian = hessian

        self.critical_points = unique_critical_points

        # parse graph connecting critical points
        for idx, line in enumerate(stdout):
            if "#cp  ncp   typ        position " in line:
                start_i = idx + 1
            elif "* Attractor connectivity matrix" in line:
                end_i = idx - 2
        # if start_i and end_i haven't been found, we
        # need to re-evaluate assumptions in this parser!

        for idx, line in enumerate(stdout):
            if start_i <= idx <= end_i:
                split = line.replace("(", "").replace(")", "").split()

                idx = int(split[0]) - 1
                unique_idx = int(split[1]) - 1
                frac_coords = [float(split[3]), float(split[4]), float(split[5])]

                self._add_node(idx, unique_idx, frac_coords)
                if len(split) > 6:
                    from_idx = int(split[6]) - 1
                    to_idx = int(split[10]) - 1
                    self._add_edge(
                        idx,
                        from_idx=from_idx,
                        from_lvec=(int(split[7]), int(split[8]), int(split[9])),
                        to_idx=to_idx,
                        to_lvec=(int(split[11]), int(split[12]), int(split[13])),
                    )

    def _add_node(self, idx, unique_idx, frac_coords):
        """Add information about a node describing a critical point.

        Args:
            idx: index
            unique_idx: index of unique CriticalPoint,
                used to look up more information of point (field etc.)
            frac_coords: fractional coordinates of point
        """
        self.nodes[idx] = {"unique_idx": unique_idx, "frac_coords": frac_coords}

    def _add_edge(self, idx, from_idx, from_lvec, to_idx, to_lvec):
        """Add information about an edge linking two critical points.

        This actually describes two edges:

        from_idx ------ idx ------ to_idx

        However, in practice, from_idx and to_idx will typically be
        atom nuclei, with the center node (idx) referring to a bond
        critical point. Thus, it will be more convenient to model
        this as a single edge linking nuclei with the properties
        of the bond critical point stored as an edge attribute.

        Args:
            idx: index of node
            from_idx: from index of node
            from_lvec: vector of lattice image the from node is in
                as tuple of ints
            to_idx: to index of node
            to_lvec: vector of lattice image the to node is in as
                tuple of ints
        """
        self.edges[idx] = {
            "from_idx": from_idx,
            "from_lvec": from_lvec,
            "to_idx": to_idx,
            "to_lvec": to_lvec,
        }
