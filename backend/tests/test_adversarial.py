"""What a reviewer will try: every endpoint, called without signing in, with nonsense, with hostile text,
with huge numbers, with other companies' ids. Nothing may answer with a server error or leak data."""

import itertools
import json
import uuid

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import bearer

# Endpoints anyone may call without signing in.
PUBLIC = {
    ("GET", "/health"), ("POST", "/auth/register"), ("POST", "/auth/register/code"), ("POST", "/auth/login"), ("POST", "/auth/refresh"),
    ("POST", "/auth/invites/accept"), ("POST", "/auth/password/forgot"), ("POST", "/auth/password/reset"),
    ("POST", "/auth/email/recover"), ("GET", "/receipts/verify/{token}"), ("GET", "/r/{token}"),
}

HOSTILE = [
    None, "", "   ", "a" * 20000, -1, 0, 10**30, 1.5, -99999999999.999, True, [], {}, "\u0000", "nul\u0000inside",
    "<script>alert(1)</script>", "'; DROP TABLE lr; --", "😀🚚ગુજરાતી", "../../etc/passwd", "2026-02-30", "NaN", {"$ne": 1},
]


def _operations():
    for path, item in app.openapi()["paths"].items():
        for method, op in item.items():
            yield method.upper(), path, op


def _fill(path: str, value: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + value + out[end + 1 :]
    return out


def _schema(op):
    body = op.get("requestBody", {}).get("content", {})
    if "application/json" not in body:
        return None
    schema = body["application/json"]["schema"]
    if "$ref" in schema:
        schema = app.openapi()["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def test_every_private_endpoint_needs_a_valid_sign_in(client):
    client = TestClient(app, raise_server_exceptions=False)
    failures = []
    for method, path, _ in _operations():
        if (method, path) in PUBLIC:
            continue
        url = _fill(path, str(uuid.uuid4()))
        for headers in ({}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic YWRtaW46YWRtaW4="}):
            r = client.request(method, url, headers=headers, json={})
            if r.status_code not in (401, 403):
                failures.append((method, path, headers, r.status_code))
    assert failures == []


def test_no_hostile_input_causes_a_server_error(client, admin):
    # A client that reports server errors as responses, as a real caller would see them.
    client = TestClient(app, raise_server_exceptions=False)
    h = bearer(admin)
    failures = []
    for method, path, op in _operations():
        if method == "GET" and "{" not in path and not op.get("parameters"):
            continue
        for path_value in (str(uuid.uuid4()), "not-a-uuid", "%00", "1 OR 1=1"):
            url = _fill(path, path_value)
            bodies = [None, [], "plain", {}]
            schema = _schema(op)
            if schema and "properties" in schema:
                bodies += [{name: value} for name, value in itertools.product(schema["properties"], HOSTILE)]
            for body in bodies:
                kwargs = {"content": json.dumps(body, allow_nan=True)} if body is not None else {}
                r = client.request(method, url, headers={**h, "Content-Type": "application/json"}, **kwargs)
                if r.status_code >= 500:
                    failures.append((method, path, path_value, body if not isinstance(body, dict) else list(body.items())[:1], r.status_code, r.text[:200]))
            for param in op.get("parameters", []):
                if param["in"] != "query":
                    continue
                for value in ("", "x" * 5000, "-1", "99999999999999999999", "2026-13-45", "\u0000", "<b>"):
                    r = client.request(method, url, headers=h, params={param["name"]: value})
                    if r.status_code >= 500:
                        failures.append((method, path, param["name"], value[:20], r.status_code, r.text[:200]))
    assert failures == [], "\n".join(map(str, failures[:60]))


def test_errors_never_show_internals(client, admin):
    h = bearer(admin)
    for r in (
        client.post("/lrs", content="{not json", headers={**h, "Content-Type": "application/json"}),
        client.get(f"/lrs/{uuid.uuid4()}", headers=h),
        client.get("/lrs/not-a-uuid", headers=h),
        client.post("/auth/login", json={"login": "nobody@example.com", "password": "wrong-password"}),
    ):
        text = r.text.lower()
        for leak in ("traceback", "sqlalchemy", "psycopg", "select ", "/srv/", "/home/", "line "):
            assert leak not in text, (r.request.url, r.text[:300])
