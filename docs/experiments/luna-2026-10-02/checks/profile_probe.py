"""Independent acceptance probe; execute inside a trial with uv run --frozen."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from injector import Injector
from sqlalchemy import text
from sqlmodel import SQLModel

from app import container
from app.application.mediator import ApplicationMediator
from app.infrastructure.database import get_engine, init_db
from app.presentation.api.routers import users

results = []

def check(label, condition, detail=None):
    results.append({"check": label, "passed": bool(condition), "detail": detail})

async def http(app, method, path, payload=None):
    content = b"" if payload is None else json.dumps(payload).encode()
    response = []
    delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": content, "more_body": False}
        return {"type": "http.disconnect"}
    async def send(message):
        response.append(message)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("test", 80),
    }
    try:
        await app(scope, receive, send)
    except Exception as error:
        return 599, {"exception": type(error).__name__, "message": str(error)}
    status = next(m["status"] for m in response if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in response if m["type"] == "http.response.body")
    return status, json.loads(body) if body else None

async def main():
    with TemporaryDirectory(prefix="luna-profile-probe-") as directory:
        init_db(f"sqlite+aiosqlite:///{Path(directory) / 'probe.db'}")
        injector = Injector([container.configure])
        app = FastAPI()
        app.include_router(users.router)
        app.state.mediator = injector.get(ApplicationMediator)
        engine = get_engine()
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        try:
            status, created = await http(app, "POST", "/users", {"display_name": "Before", "email": "synthetic@example.test"})
            check("existing_create_input", status == 200 and isinstance(created, dict) and "id" in created, (status, created))
            if status != 200 or "id" not in created:
                return
            uid = created["id"]
            path = f"/users/{uid}"
            status, initial = await http(app, "GET", path)
            check("new_user_empty_bio", status == 200 and initial.get("bio") == "", (status, initial))
            bio = "  first line\n second line\t "
            status, updated = await http(app, "PUT", path + "/profile", {"display_name": "After", "bio": bio})
            check("update_returns_existing_id", status == 200 and updated == {"id": uid}, (status, updated))
            status, current = await http(app, "GET", path)
            expected = {"id": uid, "display_name": "After", "email": "synthetic@example.test", "bio": bio}
            check("exact_readback_new_request", status == 200 and current == expected, (status, current))
            for label, payload, wanted_status in [
                ("bio_501_rejected", {"display_name": "Never", "bio": "x" * 501}, 400),
                ("empty_name_rejected", {"display_name": "", "bio": "Never"}, 400),
                ("padded_name_rejected", {"display_name": " After ", "bio": "Never"}, 400),
                ("long_name_rejected", {"display_name": "x" * 101, "bio": "Never"}, 400),
                ("missing_bio_rejected", {"display_name": "Never"}, 422),
                ("missing_name_rejected", {"bio": "Never"}, 422),
                ("null_bio_rejected", {"display_name": "Never", "bio": None}, 422),
                ("numeric_bio_rejected", {"display_name": "Never", "bio": 42}, 422),
            ]:
                status, body = await http(app, "PUT", path + "/profile", payload)
                check(label, status == wanted_status, (status, body))
                _, after = await http(app, "GET", path)
                check(label + "_unchanged", after == expected, after)
            status, body = await http(app, "PUT", "/users/01ARZ3NDEKTSV4RRFFQ69G5FAV/profile", {"display_name": "Unknown", "bio": ""})
            check("unknown_user_not_found", status == 404, (status, body))
            status, body = await http(app, "GET", "/users/01ARZ3NDEKTSV4RRFFQ69G5FAV")
            check("unknown_user_not_created", status == 404, (status, body))
            status, body = await http(app, "PUT", "/users/not-a-ulid/profile", {"display_name": "Unknown", "bio": ""})
            check("invalid_id_rejected", status == 400, (status, body))
            for label, valid in [("bio_500_accepted", "あ" * 500), ("empty_bio_accepted", "")]:
                status, body = await http(app, "PUT", path + "/profile", {"display_name": "After", "bio": valid})
                check(label, status == 200, (status, body))
                _, got = await http(app, "GET", path)
                check(label + "_readback", got.get("bio") == valid, got)
            _, expected = await http(app, "GET", path)
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TRIGGER reject_profile_update BEFORE UPDATE ON users BEGIN SELECT RAISE(ABORT, 'probe write rejection'); END"))
            status, body = await http(app, "PUT", path + "/profile", {"display_name": "Never", "bio": "Never"})
            check("storage_failure_not_success", status in {409, 500}, (status, body))
            _, after = await http(app, "GET", path)
            check("storage_failure_unchanged", after == expected, after)
        finally:
            await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
    print(json.dumps({"checks": results, "passed": sum(x["passed"] for x in results), "total": len(results)}, ensure_ascii=False, indent=2))
