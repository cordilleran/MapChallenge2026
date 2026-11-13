"""sim.runon() is a vectorised rewrite of a Landlab rule, so it must give LossyFlowAccumulator's discharge on the same grid, receivers and loss."""
import sys
from pathlib import Path

import numpy as np
from landlab import RasterModelGrid
from landlab.components import LossyFlowAccumulator
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # day-10/, where sim.py lives
import sim  # noqa: E402


def loss_above(cap):
    """LossyFlowAccumulator's loss rule with a per-node capacity (it calls loss_function(q, node))."""
    return lambda q, n: max(q - cap[n], 0.0)


def test_runon_matches_lossy_flow_accumulator():
    rng = np.random.default_rng(1)
    for shape in [(30, 20), (120, 120)]:
        g = RasterModelGrid(shape, xy_spacing=5.0)
        g.add_field("topographic__elevation", g.y_of_node * 0.1 + rng.random(g.number_of_nodes) * 0.3, at="node")
        g.set_closed_boundaries_at_grid_edges(True, True, True, False)
        runoff = g.add_field("water__unit_flux_in", rng.random(g.number_of_nodes), at="node")
        cap = rng.random(g.number_of_nodes) * 40.0
        la = LossyFlowAccumulator(g, flow_director="D8", loss_function=loss_above(cap))
        la.run_one_step()
        r = g.at_node["flow__receiver_node"]
        area = np.full(g.number_of_nodes, 25.0); area[g.boundary_nodes] = 0.0
        q = sim.runon(runoff * area, r, sim.depth_groups(r), cap)
        np.testing.assert_allclose(q, g.at_node["surface_water__discharge"], rtol=1e-12, atol=1e-9)


def test_runon_without_capacity_is_plain_accumulation():
    g = RasterModelGrid((40, 30), xy_spacing=5.0)
    g.add_field("topographic__elevation", g.y_of_node * 0.1 + np.random.default_rng(2).random(g.number_of_nodes), at="node")
    g.set_closed_boundaries_at_grid_edges(True, True, True, False)
    g.add_ones("water__unit_flux_in", at="node")
    la = LossyFlowAccumulator(g, flow_director="D8")
    la.run_one_step()
    r = g.at_node["flow__receiver_node"]
    area = np.full(g.number_of_nodes, 25.0); area[g.boundary_nodes] = 0.0
    q = sim.runon(area.copy(), r, sim.depth_groups(r), np.zeros(g.number_of_nodes))
    np.testing.assert_allclose(q, g.at_node["surface_water__discharge"], rtol=1e-12)


if __name__ == "__main__":
    test_runon_matches_lossy_flow_accumulator()
    test_runon_without_capacity_is_plain_accumulation()
    print("ok")
