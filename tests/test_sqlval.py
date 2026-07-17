"""sqlval — the validate_sql SQL dialect (MCP §6.6, MCP-R6/R7, MT-8).

Every refusal-set vector from the security review's MCP-R7 list gets a
named case; the resolution checks pin MT-8's "citing the object"
requirement.
"""

import hashlib
import json
import subprocess
import sys

from sqlval import validate_statement

OBJECTS = [
    {"schema": "public", "name": "orders", "kind": "table",
     "columns": ["id", "user_id", "status", "net", "created_at"]},
    {"schema": "public", "name": "users", "kind": "table",
     "columns": ["id", "email", "full_name"]},
    {"schema": "reporting", "name": "v_net_sales", "kind": "view",
     "columns": ["region", "net_total"]},
]


def run(statement: str, **overrides):
    request = {
        "statement": statement,
        "engine": "postgres",
        "system": "supabase",
        "default_schema": "public",
        "objects": OBJECTS,
    }
    request.update(overrides)
    return validate_statement(request)


def codes(verdict):
    return [f["code"] for f in verdict["findings"]]


# -- pass path ---------------------------------------------------------------

def test_clean_select_passes_with_statement_hash():
    stmt = "SELECT id, status FROM orders WHERE status = 'paid'"
    v = run(stmt)
    assert v["verdict"] == "pass"
    assert v["statement_sha256"] == hashlib.sha256(stmt.encode()).hexdigest()
    assert v["referenced_objects"] == ["supabase.public.orders"]


def test_join_with_aliases_and_qualified_schema_passes():
    v = run(
        "SELECT o.id, u.email, r.net_total FROM orders o "
        "JOIN users u ON u.id = o.user_id "
        "JOIN reporting.v_net_sales r ON r.region = o.status"
    )
    assert v["verdict"] == "pass"
    assert "supabase.reporting.v_net_sales" in v["referenced_objects"]


def test_cte_of_selects_passes():
    v = run("WITH recent AS (SELECT id, net FROM orders) SELECT sum(net) FROM recent")
    assert v["verdict"] == "pass"


# -- MCP-R6: statement multiplicity ------------------------------------------

def test_mcp_r6_two_statement_batch_refused():
    v = run("SELECT 1; DROP TABLE orders")
    assert v["verdict"] == "fail"
    assert codes(v) == ["multi_statement"]


def test_mcp_r6_two_selects_also_refused():
    v = run("SELECT id FROM orders; SELECT id FROM users")
    assert v["verdict"] == "fail"
    assert codes(v) == ["multi_statement"]


# -- MCP-R7: parser-decided refusal set --------------------------------------

def test_mcp_r7_cte_wrapped_write_refused():
    v = run("WITH x AS (DELETE FROM orders RETURNING id) SELECT count(*) FROM x")
    assert v["verdict"] == "fail"
    assert "statement_class" in codes(v)


def test_mcp_r7_plain_write_refused():
    for stmt in ("DELETE FROM orders", "UPDATE orders SET status = 'x'",
                 "INSERT INTO orders (id) VALUES (1)", "DROP TABLE orders",
                 "CREATE TABLE t (id int)", "TRUNCATE orders"):
        v = run(stmt)
        assert v["verdict"] == "fail", stmt
        assert "statement_class" in codes(v), stmt


def test_mcp_r7_select_for_update_refused():
    v = run("SELECT id FROM orders FOR UPDATE")
    assert v["verdict"] == "fail"
    assert "locking_clause" in codes(v)


def test_mcp_r7_copy_and_do_refused():
    for stmt in ("COPY orders TO '/tmp/x'", "DO $$ BEGIN NULL; END $$"):
        v = run(stmt)
        assert v["verdict"] == "fail", stmt
        assert codes(v)[0] in ("statement_class", "parse_error"), stmt


def test_mcp_r7_side_effecting_functions_refused():
    v = run("SELECT pg_read_file('/etc/passwd')")
    assert v["verdict"] == "fail"
    assert "denied_function" in codes(v)
    v = run("SELECT pg_sleep(10) FROM orders")
    assert "denied_function" in codes(v)


def test_conventions_extra_denylist_merges():
    v = run("SELECT my_side_effect(id) FROM orders", denied_functions=["my_side_effect"])
    assert v["verdict"] == "fail"
    assert "denied_function" in codes(v)


# -- MT-8: resolution against the snapshot surface ---------------------------

def test_mt8_unknown_object_cited():
    v = run("SELECT id FROM shipments")
    assert v["verdict"] == "fail"
    f = v["findings"][0]
    assert f["code"] == "unknown_object"
    assert f["ref"] == "supabase.public.shipments"


def test_mt8_dropped_column_cited_with_object():
    v = run("SELECT legacy_flag FROM orders")
    assert v["verdict"] == "fail"
    f = v["findings"][0]
    assert f["code"] == "unknown_column"
    assert f["ref"] == "supabase.public.orders"
    assert "legacy_flag" in f["message"]


def test_select_star_resolves_via_schema():
    v = run("SELECT * FROM orders")
    assert v["verdict"] == "pass"


# -- CLI ---------------------------------------------------------------------

def test_cli_verdict_and_exit_codes(tmp_path):
    req = tmp_path / "req.json"
    req.write_text(json.dumps({
        "statement": "SELECT id FROM orders",
        "system": "supabase",
        "objects": OBJECTS,
    }))
    proc = subprocess.run([sys.executable, "-m", "sqlval", str(req)],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["verdict"] == "pass"

    req.write_text(json.dumps({
        "statement": "SELECT 1; SELECT 2",
        "system": "supabase",
        "objects": OBJECTS,
    }))
    proc = subprocess.run([sys.executable, "-m", "sqlval", str(req)],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["verdict"] == "fail"
