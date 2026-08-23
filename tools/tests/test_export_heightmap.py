"""8-bit heightmap export must clamp, never wrap, tall engine-height columns."""

import numpy as np
from PIL import Image

from realearth.export_7dtd import export_heightmap_png


def test_export_heightmap_8bit_clamps_above_255(tmp_path):
    # one_to_one profile output is int32 with real meters (Everest ≈ 8949);
    # a plain astype(uint8) would persist 8949 % 256 = 69 (below sea level).
    game_y = np.array([[0], [255], [256], [300], [8949]], dtype=np.int32)
    path = tmp_path / "heightmap_8bit.png"
    export_heightmap_png(game_y, path, bit16=False)
    back = np.asarray(Image.open(path))
    assert back.dtype == np.uint8
    assert back.ravel().tolist() == [0, 255, 255, 255, 255]


def test_export_heightmap_16bit_saturates_instead_of_wrapping(tmp_path):
    game_y = np.array([[8949]], dtype=np.int32)
    path = tmp_path / "heightmap.png"
    export_heightmap_png(game_y, path, bit16=True)
    back = np.asarray(Image.open(path))
    assert back.dtype == np.uint16
    assert int(back[0, 0]) == 65535


def test_export_heightmap_8bit_rounds_fractional_floats(tmp_path):
    game_y = np.array([[100.4, 100.5, 100.6]])
    path = tmp_path / "heightmap_8bit.png"
    export_heightmap_png(game_y, path, bit16=False)
    back = np.asarray(Image.open(path))
    assert back.ravel().tolist() == [100, 100, 101]
