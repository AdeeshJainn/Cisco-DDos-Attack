"""The committed dashboard schema must always match the pydantic models —
drift turns this test (and the dashboard type build) red."""

import json
from pathlib import Path

from argus import contracts as c

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "dashboard" / "src" / "contracts" / "schema.json"
)


def test_schema_covers_every_registry_entry():
    schema = c.export_json_schema()
    assert set(schema["properties"]) == set(c.CONTRACT_MODELS)


def test_committed_schema_matches_models():
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    regenerated = c.export_json_schema()
    assert committed == regenerated, (
        "dashboard/src/contracts/schema.json is stale — regenerate with "
        "`python -m argus.contracts export` and `npm run gen:contracts`"
    )
