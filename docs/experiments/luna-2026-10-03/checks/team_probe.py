"""Independent ASGI acceptance checks, derived from baseline and task prompts."""

import argparse
import json
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import anyio

RESULTS: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: Any = None) -> None:
    """Record a check without losing later independent failures."""
    RESULTS.append({"check": name, "passed": bool(passed), "detail": detail})


async def http(
    app: Any, method: str, path: str, payload: Any = None
) -> tuple[int, Any]:
    """Execute the registered ASGI stack; unexpected exceptions fail the probe."""
    content = b"" if payload is None else json.dumps(payload).encode()
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": content, "more_body": False}
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    with anyio.fail_after(15):
        await app(scope, receive, send)
    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert len(starts) == 1, messages
    bodies = [m for m in messages if m["type"] == "http.response.body"]
    assert bodies and not bodies[-1].get("more_body", False), messages
    body = b"".join(m.get("body", b"") for m in bodies)
    return starts[0]["status"], json.loads(body) if body else None


def contract_shape(value: Any, document: dict[str, Any]) -> Any:
    """Resolve local references and omit documentation-only OpenAPI metadata."""
    if isinstance(value, list):
        return [contract_shape(item, document) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        assert reference.startswith("#/"), reference
        resolved: Any = document
        for part in reference[2:].split("/"):
            resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
        value = {**resolved, **{k: v for k, v in value.items() if k != "$ref"}}
    documentation = {
        "title",
        "description",
        "summary",
        "operationId",
        "tags",
        "example",
        "examples",
        "externalDocs",
    }
    return {
        key: (
            {name: contract_shape(prop, document) for name, prop in item.items()}
            if key == "properties"
            else contract_shape(item, document)
        )
        for key, item in value.items()
        if key not in documentation
    }


def openapi_checks(schema: dict[str, Any], field: str) -> None:
    """Compare public contract meaning, allowing documentation-only edits."""
    baseline = json.loads(Path(__file__).with_name("baseline_openapi.json").read_text())
    comparable = json.loads(json.dumps(schema))
    actual_schemas = comparable.get("components", {}).get("schemas", {})
    team = actual_schemas.get("TeamResponse", {})
    added = team.get("properties", {}).pop(field, None)
    required = team.get("required", [])
    if field in required:
        required.remove(field)
    check("openapi_get_new_string", bool(added) and added.get("type") == "string")
    for path, operations in baseline["paths"].items():
        for method, operation in operations.items():
            actual = comparable.get("paths", {}).get(path, {}).get(method)
            check(
                f"openapi_endpoint:{method}:{path}",
                contract_shape(actual, comparable)
                == contract_shape(operation, baseline),
            )
    for name, expected in baseline["components"]["schemas"].items():
        actual = actual_schemas.get(name)
        check(
            f"openapi_schema:{name}",
            contract_shape(actual, comparable) == contract_shape(expected, baseline),
        )
    operation = (
        schema.get("paths", {}).get(f"/teams/{{team_id}}/{field}", {}).get("put")
    )
    check("openapi_new_route", isinstance(operation, dict))


async def run(field: str, maximum: int) -> bool:
    """Exercise HTTP operations against a disposable persisted database."""
    from injector import Injector
    from sqlalchemy import text
    from sqlmodel import SQLModel

    from app import container
    from app.application.mediator import ApplicationMediator
    from app.contracts.ports import IUnitOfWork
    from app.domain.aggregates.team import Team
    from app.domain.value_objects import TeamId
    from app.infrastructure.database import get_engine, init_db
    from app.presentation.api.__main__ import app

    with TemporaryDirectory(prefix="luna-team-acceptance-") as directory:
        init_db(f"sqlite+aiosqlite:///{Path(directory) / 'probe.db'}")
        injector = Injector([container.configure])
        app.state.mediator = injector.get(ApplicationMediator)
        engine = get_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
            status, schema = await http(app, "GET", "/openapi.json")
            check("openapi_http", status == 200)
            openapi_checks(schema, field)
            status, created = await http(app, "POST", "/teams", {"name": "Before"})
            check(
                "create_original_input",
                status == 200 and set(created) == {"id"},
                created,
            )
            if status != 200 or not isinstance(created, dict) or "id" not in created:
                raise AssertionError(
                    "Cannot run dependent checks: team creation failed"
                )
            tid = created["id"]
            path = f"/teams/{tid}"
            update_path = f"{path}/{field}"

            async def read(label: str) -> dict[str, Any]:
                status, body = await http(app, "GET", path)
                check(label + "_http", status == 200, (status, body))
                check(
                    label + "_existing_keys",
                    isinstance(body, dict)
                    and body.get("id") == tid
                    and isinstance(body.get("name"), str)
                    and type(body.get("version")) is int,
                    body,
                )
                return body

            async def persisted(label: str, expected: dict[str, Any]) -> None:
                # A fresh injector and UoW cannot reuse request identity-map state.
                fresh = Injector([container.configure]).get(IUnitOfWork)
                async with fresh as uow:
                    result = await uow.GetRepository(Team, TeamId).get_by_id(
                        TeamId.from_primitive(tid).unwrap()
                    )
                    team = result.unwrap()
                    value = getattr(team, field)
                    if hasattr(value, "to_primitive"):
                        value = value.to_primitive()
                    check(label + "_new_uow", value == expected[field])
                    check(
                        label + "_new_uow_existing_keys",
                        team.id.to_primitive() == expected["id"]
                        and team.name.to_primitive() == expected["name"]
                        and team.version.to_primitive() == expected["version"],
                    )

            initial = await read("initial")
            check("new_team_empty", initial.get(field) == "", initial)
            check(
                "new_team_name_version",
                initial.get("name") == "Before" and initial.get("version") == 0,
                initial,
            )
            previous_version = initial["version"]
            for label, value in [
                ("whitespace_newline", "  first line\n second line\t \r\n"),
                ("maximum_unicode", "あ" * maximum),
                ("empty", ""),
            ]:
                status, body = await http(app, "PUT", update_path, {field: value})
                check(
                    label + "_update",
                    status == 200 and body == {"id": tid},
                    (status, body),
                )
                current = await read(label)
                check(
                    label + "_exact",
                    current.get(field) == value and current.get("name") == "Before",
                    current,
                )
                check(
                    label + "_version_increment",
                    current.get("version") == previous_version + 1,
                )
                previous_version = current["version"]
                await persisted(label, current)
            value = "  retained\n after rename\t "
            status, body = await http(app, "PUT", update_path, {field: value})
            check("before_rename_update", status == 200 and body == {"id": tid})
            status, body = await http(app, "PUT", path, {"name": "After"})
            check(
                "rename_original_input",
                status == 200 and body == {"id": tid},
                (status, body),
            )
            expected = await read("renamed")
            check(
                "rename_preserves_value",
                expected.get(field) == value and expected.get("name") == "After",
                expected,
            )
            check(
                "rename_version_increment",
                expected.get("version") == previous_version + 2,
            )
            await persisted("rename", expected)
            invalid = [
                ("oversize", {field: "あ" * (maximum + 1)}, 400),
                ("missing", {}, 422),
            ]
            invalid += [
                (f"type_{type(v).__name__}", {field: v}, 422)
                for v in [None, 42, True, 1.5, [], {}]
            ]
            for label, payload, wanted in invalid:
                status, body = await http(app, "PUT", update_path, payload)
                check(label + "_status", status == wanted, (status, body))
                after = await read(label)
                check(label + "_unchanged", after == expected, after)
            for method in ["POST", "PUT"]:
                target = "/teams" if method == "POST" else path
                for label, payload, wanted in [
                    ("missing", {}, 422),
                    ("type", {"name": 42}, 422),
                    ("empty", {"name": ""}, 400),
                ]:
                    status, body = await http(app, method, target, payload)
                    check(f"legacy_{method}_{label}", status == wanted, (status, body))
            check("legacy_invalid_unchanged", await read("legacy_invalid") == expected)
            unknown = "/teams/01ARZ3NDEKTSV4RRFFQ69G5FAV"
            for label, method, target, payload, wanted in [
                ("unknown_update", "PUT", f"{unknown}/{field}", {field: ""}, 404),
                ("unknown_not_created", "GET", unknown, None, 404),
                ("invalid_id", "PUT", f"/teams/not-a-ulid/{field}", {field: ""}, 400),
            ]:
                status, body = await http(app, method, target, payload)
                check(label, status == wanted, (status, body))
            async with engine.connect() as connection:
                before_failure = (
                    (
                        await connection.execute(
                            text("SELECT * FROM teams WHERE id = :id"), {"id": tid}
                        )
                    )
                    .mappings()
                    .one()
                )
            # Trigger abort tests flush failure, not a commit-only failure.
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "CREATE TRIGGER reject_team_update BEFORE UPDATE ON teams "
                        "BEGIN SELECT RAISE(ABORT, 'independent probe rejection'); END"
                    )
                )
            status, body = await http(app, "PUT", update_path, {field: "Never saved"})
            check("storage_failure_http", status == 409, (status, body))
            after = await read("storage_failure")
            check("storage_failure_unchanged", after == expected, after)
            await persisted("storage_failure", expected)
            async with engine.connect() as connection:
                after_failure = (
                    (
                        await connection.execute(
                            text("SELECT * FROM teams WHERE id = :id"), {"id": tid}
                        )
                    )
                    .mappings()
                    .one()
                )
            check(
                "storage_failure_all_db_columns",
                dict(after_failure) == dict(before_failure),
            )
        finally:
            await engine.dispose()
    return True


def main() -> None:
    """Report failures as JSON and nonzero exit; never treat omissions as passes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("field", choices=["description", "tagline"])
    parser.add_argument("maximum", type=int)
    args = parser.parse_args()
    try:
        if args.maximum != {"description": 2000, "tagline": 160}[args.field]:
            raise ValueError("Maximum does not match the frozen task contract")
        check(
            "all_scenarios_completed", anyio.run(run, args.field, args.maximum) is True
        )
    except Exception as error:
        check(
            "probe_exception",
            False,
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
    passed = sum(item["passed"] for item in RESULTS)
    print(
        "PROBE_JSON="
        + json.dumps(
            {
                "checks": RESULTS,
                "passed": passed,
                "total": len(RESULTS),
                "human_time_saved": "not measured",
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0 if RESULTS and passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
