"""Looker Studio connector assembly: manifest + the publish handler.

Publisher-only — no metadata capability, deliberately: Looker Studio is
a publish *target*, not a context source; nothing about it belongs in a
snapshot. Addressed by the runner service as
`connectors.looker_studio.connector:connector`.
"""

from pathlib import Path

from connectors.sdk.connector import Connector
from connectors.looker_studio.publisher import LookerStudioPublisher

connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"publish": LookerStudioPublisher()},
)
