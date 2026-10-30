from __future__ import annotations

import pytest

from robot_data_studio.config import settings
from robot_data_studio.db import initialize


@pytest.fixture
def isolated_settings(tmp_path):
    original = (settings.db_path, settings.data_root, settings.clothtwin_root)
    object.__setattr__(settings, "db_path", tmp_path / "studio.db")
    object.__setattr__(settings, "data_root", tmp_path / "data")
    object.__setattr__(settings, "clothtwin_root", tmp_path / "ClothTwin")
    settings.clothtwin_root.mkdir()
    initialize()
    try:
        yield settings
    finally:
        object.__setattr__(settings, "db_path", original[0])
        object.__setattr__(settings, "data_root", original[1])
        object.__setattr__(settings, "clothtwin_root", original[2])
