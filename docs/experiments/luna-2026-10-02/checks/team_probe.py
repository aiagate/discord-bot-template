"""Independent acceptance probe for the held-out team description feature."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from injector import Injector
from sqlalchemy import text
from sqlmodel import SQLModel
from profile_probe import http

from app import container
from app.application.mediator import ApplicationMediator
from app.infrastructure.database import get_engine, init_db
from app.presentation.api.routers import teams

results = []
def check(label, condition, detail=None):
    results.append({"check": label, "passed": bool(condition), "detail": detail})

async def main():
    with TemporaryDirectory(prefix="luna-team-probe-") as directory:
        init_db(f"sqlite+aiosqlite:///{Path(directory) / 'probe.db'}")
        injector = Injector([container.configure])
        app = FastAPI()
        app.include_router(teams.router)
        app.state.mediator = injector.get(ApplicationMediator)
        engine = get_engine()
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        try:
            status, created = await http(app, "POST", "/teams", {"name": "Before"})
            check("existing_create_input", status == 200 and isinstance(created, dict) and "id" in created, (status, created))
            if status != 200 or "id" not in created:
                return
            tid = created["id"]
            path = f"/teams/{tid}"
            status, initial = await http(app, "GET", path)
            check("new_team_empty_description", status == 200 and initial.get("description") == "", (status, initial))
            description = "  first line\n second line\t "
            status, updated = await http(app, "PUT", path + "/description", {"description": description})
            check("update_returns_existing_id", status == 200 and updated == {"id": tid}, (status, updated))
            status, current = await http(app, "GET", path)
            check("description_readback_new_request", status == 200 and current.get("description") == description and current.get("name") == "Before" and current.get("id") == tid, (status, current))
            status, renamed = await http(app, "PUT", path, {"name": "After"})
            check("existing_rename_input", status == 200 and renamed == {"id": tid}, (status, renamed))
            _, expected = await http(app, "GET", path)
            check("rename_preserves_description", expected.get("description") == description and expected.get("name") == "After", expected)
            for label, payload, wanted_status in [
                ("description_2001_rejected", {"description": "x" * 2001}, 400),
                ("missing_description_rejected", {}, 422),
                ("null_description_rejected", {"description": None}, 422),
                ("numeric_description_rejected", {"description": 42}, 422),
            ]:
                status, body = await http(app, "PUT", path + "/description", payload)
                check(label, status == wanted_status, (status, body))
                _, after = await http(app, "GET", path)
                check(label + "_unchanged", after == expected, after)
            status, body = await http(app, "PUT", "/teams/01ARZ3NDEKTSV4RRFFQ69G5FAV/description", {"description": ""})
            check("unknown_team_not_found", status == 404, (status, body))
            status, body = await http(app, "GET", "/teams/01ARZ3NDEKTSV4RRFFQ69G5FAV")
            check("unknown_team_not_created", status == 404, (status, body))
            status, body = await http(app, "PUT", "/teams/not-a-ulid/description", {"description": ""})
            check("invalid_id_rejected", status == 400, (status, body))
            for label, valid in [("description_2000_accepted", "あ" * 2000), ("empty_description_accepted", "")]:
                status, body = await http(app, "PUT", path + "/description", {"description": valid})
                check(label, status == 200, (status, body))
                _, got = await http(app, "GET", path)
                check(label + "_readback", got.get("description") == valid and got.get("name") == "After", got)
            _, expected = await http(app, "GET", path)
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TRIGGER reject_description_update BEFORE UPDATE ON teams BEGIN SELECT RAISE(ABORT, 'probe write rejection'); END"))
            status, body = await http(app, "PUT", path + "/description", {"description": "Never"})
            check("storage_failure_not_success", status in {409, 500}, (status, body))
            _, after = await http(app, "GET", path)
            check("storage_failure_unchanged", after == expected, after)
        finally:
            await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
    print(json.dumps({"checks": results, "passed": sum(x["passed"] for x in results), "total": len(results)}, ensure_ascii=False, indent=2))
