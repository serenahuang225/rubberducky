"""Logical board geometry shared by tutor tools, student strokes and the scene API.

The board is a fixed logical coordinate space; clients scale it uniformly to their viewport.
The student pen has one fixed width and the server, never the client, assigns pen width and
color roles, so a draft cannot spoof authorship or an arbitrary brush.
"""

from typing import Annotated

from pydantic import Field

from app.schemas.common import ContractModel

BOARD_WIDTH = 1600.0
BOARD_HEIGHT = 1200.0
PEN_WIDTH = 3.0
MAX_PATH_POINTS = 200
MIN_SHAPE_EXTENT = 2.0


class Point(ContractModel):
    """One logical board point. Non-finite and out-of-board coordinates are rejected."""

    x: Annotated[float, Field(ge=0.0, le=BOARD_WIDTH, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=0.0, le=BOARD_HEIGHT, allow_inf_nan=False)]
