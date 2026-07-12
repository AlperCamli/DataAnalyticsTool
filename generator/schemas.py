"""Front-matter JSON Schemas per doc_class (KB §4, K-5; Draft 2020-12).

Closed contracts: unknown keys are rejected (§4 — docs are numerous and
typo-prone). Classes shipped here are the ones the 1.5/1.6 tree contains:
the three machine classes the generator emits, plus the §4.2 human object/
group classes (the generator reads their `status` for index roll-ups, and
task 1.7 lands them). `entity`, `metric`, and `lineage-note` schemas land
with tasks 1.8/1.9 — validation reports their doc_classes as unregistered
until then, additively per the same pattern.
"""

_PROVENANCE = {
    "generated_at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
    "source_mode": {"enum": ["ddl-file", "live", "api"]},
    "snapshot_version": {"const": "1"},
    "status": {"const": "machine"},
}
_SHA = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_PROVENANCE_REQUIRED = ["generated_at", "source_mode", "snapshot_version", "status"]

MACHINE_OBJECT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["doc_class", "object", "kind", "schema_hash", *_PROVENANCE_REQUIRED],
    "additionalProperties": False,
    "properties": {
        "doc_class": {"const": "machine-object"},
        "object": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "minLength": 1},
        "schema_hash": _SHA,
        **_PROVENANCE,
    },
}

MACHINE_GROUP = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["doc_class", "objects", *_PROVENANCE_REQUIRED],
    "additionalProperties": False,
    "properties": {
        "doc_class": {"const": "machine-group"},
        "objects": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["object", "kind", "schema_hash"],
                "additionalProperties": False,
                "properties": {
                    "object": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "minLength": 1},
                    "schema_hash": _SHA,
                },
            },
        },
        **_PROVENANCE,
    },
}

MACHINE_INDEX = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["doc_class", "system", "scope", *_PROVENANCE_REQUIRED],
    "additionalProperties": False,
    "properties": {
        "doc_class": {"const": "machine-index"},
        "system": {"type": "string", "minLength": 1},
        "scope": {"enum": ["system", "schema"]},
        "schema": {"type": "string", "minLength": 1},
        **_PROVENANCE,
    },
    "allOf": [
        {
            "if": {"properties": {"scope": {"const": "schema"}}},
            "then": {"required": ["schema"]},
            "else": {"not": {"required": ["schema"]}},
        }
    ],
}

# §4.2 — provisional strictness: required fields are the identity/trust
# core; task 1.7 (enrich) owns tightening the rest when it authors these.
_HUMAN_COMMON = {
    "object": {"type": "string", "minLength": 1},
    "written_against_schema_hash": _SHA,
    "status": {"enum": ["draft", "verified", "stale", "contaminated"]},
    "last_verified": {"type": ["string", "null"]},
    "sources": {"type": "array", "items": {"type": "string"}},
    "depends_on": {
        "type": "array",
        "items": {"anyOf": [{"type": "string"}, {"type": "object"}]},
    },
    "contamination": {"type": ["object", "null"]},
}
_HUMAN_REQUIRED = ["doc_class", "object", "written_against_schema_hash", "status"]

HUMAN_OBJECT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": _HUMAN_REQUIRED,
    "additionalProperties": False,
    "properties": {"doc_class": {"const": "human-object"}, **_HUMAN_COMMON},
}

HUMAN_GROUP = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": _HUMAN_REQUIRED,
    "additionalProperties": False,
    "properties": {"doc_class": {"const": "human-group"}, **_HUMAN_COMMON},
}

DOC_CLASS_SCHEMAS: dict[str, dict] = {
    "machine-object": MACHINE_OBJECT,
    "machine-group": MACHINE_GROUP,
    "machine-index": MACHINE_INDEX,
    "human-object": HUMAN_OBJECT,
    "human-group": HUMAN_GROUP,
}
