from __future__ import annotations

import numpy as np
from numpy.testing import assert_allclose

from pymatgen.analysis.chemenv.utils.math_utils import (
    _cartesian_product,
    cosinus_step,
    divisors,
    get_center_of_arc,
    get_linearly_independent_vectors,
    power3_step,
    powern_parts_step,
    prime_factors,
    scale_and_clamp,
    smootherstep,
    smoothstep,
)
from pymatgen.util.testing import MatSciTest

__author__ = "waroquiers"


class TestMathUtils(MatSciTest):
    def test_list_cartesian_product(self):
        list_of_lists = [[0, 1], [2, 5, 4], [5]]
        assert _cartesian_product(lists=list_of_lists) == [
            [0, 2, 5],
            [1, 2, 5],
            [0, 5, 5],
            [1, 5, 5],
            [0, 4, 5],
            [1, 4, 5],
        ]
        list_of_lists = [[0, 1], [2, 5, 4], []]
        assert _cartesian_product(lists=list_of_lists) == []
        list_of_lists = [[1], [3], [2]]
        assert _cartesian_product(lists=list_of_lists) == [[1, 3, 2]]
        list_of_lists = [[7]]
        assert _cartesian_product(lists=list_of_lists) == [[7]]

    def test_math_utils(self):
        ff = prime_factors(250)
        assert ff == [5, 5, 5, 2]
        div = divisors(560)
        assert div == [
            1,
            2,
            4,
            5,
            7,
            8,
            10,
            14,
            16,
            20,
            28,
            35,
            40,
            56,
            70,
            80,
            112,
            140,
            280,
            560,
        ]
        center = get_center_of_arc([0.0, 0.0], [1.0, 0.0], 0.5)
        assert_allclose(center, (0.5, 0.0))

    def test_linearly_independent_vectors(self):
        v1, v2, v3 = np.eye(3)
        v4 = -v1
        v5 = np.array([1, 1, 0])
        independent_vectors = get_linearly_independent_vectors([v1, v2, v3])
        assert len(independent_vectors) == 3
        independent_vectors = get_linearly_independent_vectors([v1, v2, v4])
        assert len(independent_vectors) == 2
        independent_vectors = get_linearly_independent_vectors([v1, v2, v5])
        assert len(independent_vectors) == 2
        independent_vectors = get_linearly_independent_vectors([v1, v2, v3, v4, v5])
        assert len(independent_vectors) == 3

    def test_scale_and_clamp(self):
        edge0 = 7.0
        edge1 = 11.0
        clamp0 = 0.0
        clamp1 = 1.0
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(
            scale_and_clamp(vals, edge0, edge1, clamp0, clamp1),
            [
                0.0,
                0.0,
                0.0,
                0.25,
                0.5,
                0.75,
                1.0,
                1.0,
            ],
        )

    def test_smoothstep(self):
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(smoothstep(vals, edges=[0.0, 1.0]), [1.0] * 8)
        assert_allclose(
            smoothstep(vals, edges=[7.0, 11.0]),
            [
                0.0,
                0.0,
                0.0,
                0.15625,
                0.5,
                0.84375,
                1.0,
                1.0,
            ],
        )

    def test_smootherstep(self):
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(smootherstep(vals, edges=[0.0, 1.0]), [1.0] * 8)
        assert_allclose(
            smootherstep(vals, edges=[7.0, 11.0]),
            [
                0.0,
                0.0,
                0.0,
                0.103515625,
                0.5,
                0.896484375,
                1.0,
                1.0,
            ],
        )

    def test_power3_step(self):
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(power3_step(vals, edges=[0.0, 1.0]), [1.0] * 8)
        assert_allclose(
            power3_step(vals, edges=[7.0, 11.0]),
            [
                0.0,
                0.0,
                0.0,
                0.15625,
                0.5,
                0.84375,
                1.0,
                1.0,
            ],
        )

    def test_cosinus_step(self):
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(cosinus_step(vals, edges=[0.0, 1.0]), [1.0] * 8)
        assert_allclose(
            cosinus_step(vals, edges=[7.0, 11.0]),
            [0.0, 0.0, 0.0, 0.14644660940672616, 0.5, 0.8535533905932737, 1.0, 1.0],
            5,
        )

    def test_powern_parts_step(self):
        vals = np.linspace(5.0, 12.0, num=8)
        assert_allclose(powern_parts_step(vals, edges=[0.0, 1.0], nn=2), [1.0] * 8)
        assert_allclose(powern_parts_step(vals, edges=[0.0, 1.0], nn=3), [1.0] * 8)
        assert_allclose(powern_parts_step(vals, edges=[0.0, 1.0], nn=4), [1.0] * 8)
        assert_allclose(
            powern_parts_step(vals, edges=[7.0, 11.0], nn=2),
            [
                0.0,
                0.0,
                0.0,
                0.125,
                0.5,
                0.875,
                1.0,
                1.0,
            ],
        )
        assert_allclose(
            powern_parts_step(vals, edges=[7.0, 11.0], nn=3),
            [
                0.0,
                0.0,
                0.0,
                0.0625,
                0.5,
                0.9375,
                1.0,
                1.0,
            ],
        )
        assert_allclose(
            powern_parts_step(vals, edges=[7.0, 11.0], nn=4),
            [
                0.0,
                0.0,
                0.0,
                0.03125,
                0.5,
                0.96875,
                1.0,
                1.0,
            ],
        )
