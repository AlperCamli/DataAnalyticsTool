"""Power BI connector assembly: manifest + the publish handler.

Publisher-only, like looker_studio — Power BI is a publish *target*,
not a context source; nothing about it belongs in a snapshot. Addressed
by the runner service as `connectors.powerbi.connector:connector`.
"""

from pathlib import Path

from connectors.sdk.connector import Connector
from connectors.powerbi.publisher import PowerBIPublisher

connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"publish": PowerBIPublisher()},
)
