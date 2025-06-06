"""Utilities for manipulating coordinates or list of coordinates, under periodic
boundary conditions or otherwise. Many of these are heavily vectorized in
numpy for performance.
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

import numpy as np
from monty.json import MSONable

from pymatgen.util import coord_cython

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Literal

    from numpy.typing import ArrayLike


# array size threshold for looping instead of broadcasting
LOOP_THRESHOLD = 1e6


def find_in_coord_list(coord_list, coord, atol: float = 1e-8):
    """Find the indices of matches of a particular coord in a coord_list.

    Args:
        coord_list: List of coords to test
        coord: Specific coordinates
        atol: Absolute tolerance. Defaults to 1e-8. Accepts both scalar and
            array.

    Returns:
        Indices of matches, e.g. [0, 1, 2, 3]. Empty list if not found.
    """
    if len(coord_list) == 0:
        return []
    diff = np.array(coord_list) - np.array(coord)[None, :]
    return np.where(np.all(np.abs(diff) < atol, axis=1))[0]


def in_coord_list(coord_list, coord, atol: float = 1e-8) -> bool:
    """Test if a particular coord is within a coord_list.

    Args:
        coord_list: List of coords to test
        coord: Specific coordinates
        atol: Absolute tolerance. Defaults to 1e-8. Accepts both scalar and
            array.

    Returns:
        bool: True if coord is in the coord list.
    """
    return len(find_in_coord_list(coord_list, coord, atol=atol)) > 0


def is_coord_subset(subset: ArrayLike, superset: ArrayLike, atol: float = 1e-8) -> bool:
    """Test if all coords in subset are contained in superset.
    Doesn't use periodic boundary conditions.

    Args:
        subset (ArrayLike): List of coords
        superset (ArrayLike): List of coords
        atol (float): Absolute tolerance for comparing coordinates. Defaults to 1e-8.

    Returns:
        bool: True if all of subset is in superset.
    """
    c1 = np.array(subset)
    c2 = np.array(superset)
    is_close = np.all(np.abs(c1[:, None, :] - c2[None, :, :]) < atol, axis=-1)
    any_close = np.any(is_close, axis=-1)
    return all(any_close)


def coord_list_mapping(subset: ArrayLike, superset: ArrayLike, atol: float = 1e-8):
    """Get the index mapping from a subset to a superset.
    Subset and superset cannot contain duplicate rows.

    Args:
        subset (ArrayLike): List of coords
        superset (ArrayLike): List of coords
        atol (float): Absolute tolerance. Defaults to 1e-8.

    Returns:
        list of indices such that superset[indices] = subset
    """
    c1 = np.array(subset)
    c2 = np.array(superset)
    inds = np.where(np.all(np.isclose(c1[:, None, :], c2[None, :, :], atol=atol), axis=2))[1]
    result = c2[inds]
    if not np.allclose(c1, result, atol=atol) and not is_coord_subset(subset, superset):
        raise ValueError("not a subset of superset")
    if not result.shape == c1.shape:
        raise ValueError("Something wrong with the inputs, likely duplicates in superset")
    return inds


def coord_list_mapping_pbc(subset, superset, atol: float = 1e-8, pbc: tuple[bool, bool, bool] = (True, True, True)):
    """Get the index mapping from a subset to a superset.
    Superset cannot contain duplicate matching rows.

    Args:
        subset (ArrayLike): List of frac_coords
        superset (ArrayLike): List of frac_coords
        atol (float): Absolute tolerance. Defaults to 1e-8.
        pbc (tuple): A tuple defining the periodic boundary conditions along the three
            axis of the lattice.

    Returns:
        list of indices such that superset[indices] = subset
    """
    return coord_cython.coord_list_mapping_pbc(subset, superset, np.ones(3) * atol, pbc)


def get_linear_interpolated_value(x_values: ArrayLike, y_values: ArrayLike, x: float) -> float:
    """Get an interpolated value by linear interpolation between two values.
    This method is written to avoid dependency on scipy, which causes issues on
    threading servers.

    Args:
        x_values: Sequence of x values.
        y_values: Corresponding sequence of y values
        x: Get value at particular x

    Returns:
        Value at x.
    """
    arr = np.array(sorted(zip(x_values, y_values, strict=True), key=lambda d: d[0]))  # type:ignore[arg-type,return-value]

    indices = np.where(arr[:, 0] > x)[0]

    if len(indices) == 0 or indices[0] == 0:
        raise ValueError(f"{x} is out of range of provided x_values ({min(x_values)}, {max(x_values)})")  # type:ignore[type-var,arg-type,str-bytes-safe]

    idx = indices[0]
    x1, x2 = arr[idx - 1][0], arr[idx][0]
    y1, y2 = arr[idx - 1][1], arr[idx][1]

    return y1 + (y2 - y1) / (x2 - x1) * (x - x1)


def all_distances(coords1: ArrayLike, coords2: ArrayLike) -> np.ndarray:
    """Get the distances between two lists of coordinates.

    Args:
        coords1: First set of Cartesian coordinates.
        coords2: Second set of Cartesian coordinates.

    Returns:
        2d array of Cartesian distances. E.g the distance between
        coords1[i] and coords2[j] is distances[i,j]
    """
    c1 = np.array(coords1)
    c2 = np.array(coords2)
    z = (c1[:, None, :] - c2[None, :, :]) ** 2
    return np.sum(z, axis=-1) ** 0.5


def pbc_diff(frac_coords1: ArrayLike, frac_coords2: ArrayLike, pbc: tuple[bool, bool, bool] = (True, True, True)):
    """Get the 'fractional distance' between two coordinates taking into
    account periodic boundary conditions.

    Args:
        frac_coords1: First set of fractional coordinates. e.g. [0.5, 0.6,
            0.7] or [[1.1, 1.2, 4.3], [0.5, 0.6, 0.7]]. It can be a single
            coord or any array of coords.
        frac_coords2: Second set of fractional coordinates.
        pbc: a tuple defining the periodic boundary conditions along the three
            axis of the lattice.

    Returns:
        Fractional distance. Each coordinate must have the property that
        abs(a) <= 0.5. Examples:
        pbc_diff([0.1, 0.1, 0.1], [0.3, 0.5, 0.9]) = [-0.2, -0.4, 0.2]
        pbc_diff([0.9, 0.1, 1.01], [0.3, 0.5, 0.9]) = [-0.4, -0.4, 0.11]
    """
    frac_dist = np.subtract(frac_coords1, frac_coords2)
    return frac_dist - np.round(frac_dist) * pbc


def pbc_shortest_vectors(lattice, frac_coords1, frac_coords2, mask=None, return_d2: bool = False):
    """Get the shortest vectors between two lists of coordinates taking into
    account periodic boundary conditions and the lattice.

    Args:
        lattice: lattice to use
        frac_coords1: First set of fractional coordinates. e.g. [0.5, 0.6, 0.7]
            or [[1.1, 1.2, 4.3], [0.5, 0.6, 0.7]]. It can be a single
            coord or any array of coords.
        frac_coords2: Second set of fractional coordinates.
        mask (boolean array): Mask of matches that are not allowed.
            i.e. if mask[1,2] is True, then subset[1] cannot be matched
            to superset[2]
        return_d2 (bool): whether to also return the squared distances

    Returns:
        np.ndarray: of displacement vectors from frac_coords1 to frac_coords2
            first index is frac_coords1 index, second is frac_coords2 index
    """
    return coord_cython.pbc_shortest_vectors(lattice, frac_coords1, frac_coords2, mask, return_d2)


def find_in_coord_list_pbc(
    frac_coord_list, frac_coord, atol: float = 1e-8, pbc: tuple[bool, bool, bool] = (True, True, True)
) -> np.ndarray:
    """Get the indices of all points in a fractional coord list that are
    equal to a fractional coord (with a tolerance), taking into account
    periodic boundary conditions.

    Args:
        frac_coord_list: List of fractional coords
        frac_coord: A specific fractional coord to test.
        atol: Absolute tolerance. Defaults to 1e-8.
        pbc: a tuple defining the periodic boundary conditions along the three
            axis of the lattice.

    Returns:
        Indices of matches, e.g. [0, 1, 2, 3]. Empty list if not found.
    """
    if len(frac_coord_list) == 0:
        return np.array([], dtype=np.int_)
    frac_coords = np.tile(frac_coord, (len(frac_coord_list), 1))
    frac_dist = frac_coord_list - frac_coords
    frac_dist[:, pbc] -= np.round(frac_dist)[:, pbc]
    return np.where(np.all(np.abs(frac_dist) < atol, axis=1))[0]


def in_coord_list_pbc(
    fcoord_list, fcoord, atol: float = 1e-8, pbc: tuple[bool, bool, bool] = (True, True, True)
) -> bool:
    """Test if a particular fractional coord is within a fractional coord_list.

    Args:
        fcoord_list: List of fractional coords to test
        fcoord: A specific fractional coord to test.
        atol: Absolute tolerance. Defaults to 1e-8.
        pbc: a tuple defining the periodic boundary conditions along the three
            axis of the lattice.

    Returns:
        bool: True if coord is in the coord list.
    """
    return len(find_in_coord_list_pbc(fcoord_list, fcoord, atol=atol, pbc=pbc)) > 0


def is_coord_subset_pbc(
    subset, superset, atol: float = 1e-8, mask=None, pbc: tuple[bool, bool, bool] = (True, True, True)
) -> bool:
    """Test if all fractional coords in subset are contained in superset.

    Args:
        subset (list): List of fractional coords to test
        superset (list): List of fractional coords to test against
        atol (float or size 3 array): Tolerance for matching
        mask (boolean array): Mask of matches that are not allowed.
            i.e. if mask[1,2] is True, then subset[1] cannot be matched
            to superset[2]
        pbc (tuple): a tuple defining the periodic boundary conditions along the three
            axis of the lattice.

    Returns:
        bool: True if all of subset is in superset.
    """
    c1 = np.array(subset, dtype=np.float64)
    c2 = np.array(superset, dtype=np.float64)
    mask_arr = (
        np.array(mask, dtype=np.int64) if mask is not None else np.zeros((len(subset), len(superset)), dtype=np.int64)
    )
    return coord_cython.is_coord_subset_pbc(c1, c2, np.zeros(3, dtype=np.float64) + atol, mask_arr, pbc)


def lattice_points_in_supercell(supercell_matrix):
    """Get the list of points on the original lattice contained in the
    supercell in fractional coordinates (with the supercell basis).
    e.g. [[2,0,0],[0,1,0],[0,0,1]] returns [[0,0,0],[0.5,0,0]].

    Args:
        supercell_matrix: 3x3 matrix describing the supercell

    Returns:
        numpy array of the fractional coordinates
    """
    diagonals = np.array(
        [
            [0, 0, 0],
            [0, 0, 1],
            [0, 1, 0],
            [0, 1, 1],
            [1, 0, 0],
            [1, 0, 1],
            [1, 1, 0],
            [1, 1, 1],
        ]
    )
    d_points = np.dot(diagonals, supercell_matrix)

    mins = np.min(d_points, axis=0)
    maxes = np.max(d_points, axis=0) + 1

    ar = np.arange(mins[0], maxes[0])[:, None] * np.array([1, 0, 0])[None, :]
    br = np.arange(mins[1], maxes[1])[:, None] * np.array([0, 1, 0])[None, :]
    cr = np.arange(mins[2], maxes[2])[:, None] * np.array([0, 0, 1])[None, :]

    all_points = ar[:, None, None] + br[None, :, None] + cr[None, None, :]
    all_points = all_points.reshape((-1, 3))

    frac_points = np.dot(all_points, np.linalg.inv(supercell_matrix))

    t_vecs = frac_points[np.all(frac_points < 1 - 1e-10, axis=1) & np.all(frac_points >= -1e-10, axis=1)]
    if len(t_vecs) != round(abs(np.linalg.det(supercell_matrix))):
        raise ValueError("The number of transformed vectors mismatch.")
    return t_vecs


def barycentric_coords(coords, simplex):
    """Convert a list of coordinates to barycentric coordinates, given a
    simplex with d+1 points. Only works for d >= 2.

    Args:
        coords: list of n coords to transform, shape should be (n,d)
        simplex: list of coordinates that form the simplex, shape should be
            (d+1, d)

    Returns:
        a list of barycentric coordinates (even if the original input was 1d)
    """
    coords = np.atleast_2d(coords)

    t = np.transpose(simplex[:-1, :]) - np.transpose(simplex[-1, :])[:, None]
    all_but_one = np.transpose(np.linalg.solve(t, np.transpose(coords - simplex[-1])))
    last_coord = 1 - np.sum(all_but_one, axis=-1)[:, None]
    return np.append(all_but_one, last_coord, axis=-1)


def get_angle(v1: ArrayLike, v2: ArrayLike, units: Literal["degrees", "radians"] = "degrees") -> float:
    """Calculate the angle between two vectors.

    Args:
        v1: Vector 1
        v2: Vector 2
        units: "degrees" or "radians". Defaults to "degrees".

    Returns:
        Angle between them in degrees.
    """
    d = np.dot(v1, v2) / np.linalg.norm(v1) / np.linalg.norm(v2)
    d = min(d, 1)
    d = max(d, -1)
    angle = math.acos(d)
    if units == "degrees":
        return math.degrees(angle)
    if units == "radians":
        return angle
    raise ValueError(f"Invalid {units=}")


class Simplex(MSONable):
    """A generalized simplex object. See https://wikipedia.org/wiki/Simplex.

    Attributes:
        space_dim (int): Dimension of the space. Usually, this is 1 more than the simplex_dim.
        simplex_dim (int): Dimension of the simplex coordinate space.
    """

    def __init__(self, coords) -> None:
        """Initialize a Simplex from vertex coordinates.

        Args:
            coords ([[float]]): Coords of the vertices of the simplex. e.g.
                [[1, 2, 3], [2, 4, 5], [6, 7, 8], [8, 9, 10].
        """
        self._coords = np.array(coords)
        self.space_dim, self.simplex_dim = self._coords.shape
        self.origin = self._coords[-1]
        if self.space_dim == self.simplex_dim + 1:
            # pre-compute augmented matrix for calculating bary_coords
            self._aug = np.concatenate([coords, np.ones((self.space_dim, 1))], axis=-1)
            self._aug_inv = np.linalg.inv(self._aug)

    @property
    def volume(self) -> float:
        """Volume of the simplex."""
        return abs(np.linalg.det(self._aug)) / math.factorial(self.simplex_dim)

    def bary_coords(self, point):
        """
        Args:
            point (ArrayLike): Point coordinates.

        Returns:
            Barycentric coordinations.
        """
        try:
            return np.dot(np.concatenate([point, [1]]), self._aug_inv)
        except AttributeError as exc:
            raise ValueError("Simplex is not full-dimensional") from exc

    def point_from_bary_coords(self, bary_coords: ArrayLike):
        """
        Args:
            bary_coords (ArrayLike): Barycentric coordinates (d+1, d).

        Returns:
            np.array: Point in the simplex.
        """
        try:
            return np.dot(bary_coords, self._aug[:, :-1])
        except AttributeError as exc:
            raise ValueError("Simplex is not full-dimensional") from exc

    def in_simplex(self, point: Sequence[float], tolerance: float = 1e-8) -> bool:
        """Check if a point is in the simplex using the standard barycentric
        coordinate system algorithm.

        Taking an arbitrary vertex as an origin, we compute the basis for the
        simplex from this origin by subtracting all other vertices from the
        origin. We then project the point into this coordinate system and
        determine the linear decomposition coefficients in this coordinate
        system. If the coeffs satisfy all(coeffs >= 0), the composition
        is in the facet.

        Args:
            point (list[float]): Point to test
            tolerance (float): Tolerance to test if point is in simplex.
        """
        return (self.bary_coords(point) >= -tolerance).all()

    def line_intersection(self, point1: Sequence[float], point2: Sequence[float], tolerance: float = 1e-8):
        """Compute the intersection points of a line with a simplex.

        Args:
            point1 (Sequence[float]): 1st point to determine the line.
            point2 (Sequence[float]): 2nd point to determine the line.
            tolerance (float): Tolerance for checking if an intersection is in the simplex. Defaults to 1e-8.

        Returns:
            points where the line intersects the simplex (0, 1, or 2).
        """
        b1 = self.bary_coords(point1)
        b2 = self.bary_coords(point2)
        line = b1 - b2
        # don't use barycentric dimension where line is parallel to face
        valid = np.abs(line) > 1e-10
        # array of all the barycentric coordinates on the line where
        # one of the values is 0
        possible = b1 - (b1[valid] / line[valid])[:, None] * line
        barys: list = []
        for p in possible:
            # it's only an intersection if its in the simplex
            if (p >= -tolerance).all():
                found = False
                # don't return duplicate points
                for b in barys:
                    if np.allclose(b, p, atol=tolerance, rtol=0):
                        found = True
                        break
                if not found:
                    barys.append(p)
        if len(barys) >= 3:
            raise ValueError("More than 2 intersections found")
        return [self.point_from_bary_coords(b) for b in barys]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Simplex):
            return NotImplemented
        return any(np.allclose(p, other.coords) for p in itertools.permutations(self._coords))

    def __hash__(self) -> int:
        return len(self._coords)

    def __repr__(self) -> str:
        output = [f"{self.simplex_dim}-simplex in {self.space_dim}D space\nVertices:"]
        output += [f"\t({', '.join(map(str, coord))})" for coord in self._coords]
        return "\n".join(output)

    @property
    def coords(self) -> np.ndarray:
        """A copy of the vertex coordinates in the simplex."""
        return self._coords.copy()
