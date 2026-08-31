import numpy as np
from transient_pipeline.config import FrozenMethod
from transient_pipeline.detector import detect_array


def test_both_polarities_and_edges():
    rng = np.random.default_rng(1234)
    image = rng.normal(1000.0, 2.0, size=(200, 200))
    # Compact opposite-polarity injected peaks well away from the edge.
    image[80, 90] += 80
    image[120, 130] -= 80
    # Edge peak must be excluded.
    image[5, 5] += 100
    d = detect_array(image, FrozenMethod())
    pts = set(zip(d["y"].tolist(), d["x"].tolist()))
    assert (80, 90) in pts
    assert (120, 130) in pts
    assert (5, 5) not in pts
    pol = {pt: int(p) for pt, p in zip(zip(d["y"], d["x"]), d["polarity"])}
    assert pol[(80, 90)] == 1
    assert pol[(120, 130)] == -1
