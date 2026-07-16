"""Test-only connector: the static demo's objects behind a configurable
sleep. Exists to hold a job mid-execution so transport tests can stage
lease expiry and mid-job kills (JC-3/JC-4) against deterministic output
— re-execution after a kill must deliver the identical canonical body.
"""

import time
from pathlib import Path

from connectors.sdk import Connector, IntrospectionResult, MetadataProvider
from connectors.static_demo.connector import _emails_view, _users_table


class SlowDemoMetadata(MetadataProvider):
    def introspect(self, config: dict) -> IntrospectionResult:
        time.sleep(float(config.get("sleep_s", 0)))
        return IntrospectionResult(
            system_class="sql",
            objects=[_users_table(), _emails_view()],
            source_properties={"engine": "static-demo"},
        )


connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"metadata": SlowDemoMetadata()},
)
