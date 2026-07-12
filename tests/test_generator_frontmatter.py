"""Front-matter byte contract: strict emission, strict parsing (KB §4, D-37)."""

from generator import frontmatter


def test_emit_quoting_rules():
    text = frontmatter.emit(
        [
            ("doc_class", "machine-object"),
            ("object", "supabase.public.orders"),
            ("kind", "table"),
            ("schema_hash", "sha256:" + "0" * 64),
            ("generated_at", "2026-07-11"),
            ("source_mode", "ddl-file"),
            ("snapshot_version", "1"),
            ("status", "machine"),
        ]
    )
    lines = text.splitlines()
    assert lines[0] == "---" and lines[-1] == "---"
    assert "object: supabase.public.orders" in lines  # plain-safe stays plain
    assert f'schema_hash: "sha256:{"0" * 64}"' in lines  # colon → quoted
    assert "generated_at: 2026-07-11" in lines  # date stays unquoted (§4.1)
    assert 'snapshot_version: "1"' in lines  # digit string → quoted


def test_emit_roster_matches_spec_shape():
    text = frontmatter.emit(
        [
            ("doc_class", "machine-group"),
            (
                "objects",
                [
                    {
                        "object": "ga4.custom.customEvent:plan_tier",
                        "kind": "api_dimension",
                        "schema_hash": "sha256:" + "a" * 64,
                    }
                ],
            ),
            ("generated_at", "2026-07-11"),
            ("source_mode", "api"),
            ("snapshot_version", "1"),
            ("status", "machine"),
        ]
    )
    assert (
        '  - { object: "ga4.custom.customEvent:plan_tier", kind: api_dimension, '
        f'schema_hash: "sha256:{"a" * 64}" }}' in text
    )


def test_split_round_trips_and_normalizes_dates():
    emitted = frontmatter.emit(
        [("doc_class", "machine-object"), ("generated_at", "2026-07-11")]
    )
    fm, body = frontmatter.split(emitted + "\nbody text\n")
    assert fm == {"doc_class": "machine-object", "generated_at": "2026-07-11"}
    assert body == "\nbody text\n"


def test_split_without_front_matter_returns_none():
    assert frontmatter.split("# just markdown\n") == (None, "# just markdown\n")


def test_split_with_broken_yaml_returns_none():
    text = "---\n{ not: [valid\n---\n\nbody\n"
    fm, body = frontmatter.split(text)
    assert fm is None and body == text
