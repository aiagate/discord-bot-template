"""Self-check reporting, exit semantics and OpenAPI normalization without trials."""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any

root = Path(__file__).resolve().parent
for name in ["team_probe", "team_migration_probe"]:
    spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for field, maximum in [("description", 2000), ("tagline", 160)]:
        for mode in ["success", "false", "early_return", "exception"]:
            module.RESULTS.clear()

            def work(
                *args: object, mode: str = mode, module: Any = module
            ) -> bool | None:
                if mode == "exception":
                    raise RuntimeError("deliberate selfcheck exception")
                module.check("synthetic_result", mode != "false")
                return None if mode == "early_return" else True

            async def async_work(*args: object, fn: Any = work) -> bool | None:
                return fn(*args)

            module.run = async_work if name == "team_probe" else work
            sys.argv = [name, field, str(maximum)]
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    module.main()
            except SystemExit as error:
                expected = 0 if mode == "success" else 1
                assert error.code == expected, (name, field, mode, error.code)
            else:
                raise AssertionError("main did not exit")
            assert "PROBE_JSON=" in output.getvalue()
            print(f"{name} {field} {mode}: exit {expected} OK")
    if name == "team_probe":
        baseline: dict[str, Any] = {
            "components": {
                "schemas": {
                    "Example": {
                        "type": "object",
                        "required": ["description"],
                        "properties": {
                            "description": {"type": "string", "title": "Old"}
                        },
                    }
                }
            }
        }
        original = module.contract_shape(
            {"$ref": "#/components/schemas/Example"}, baseline
        )
        assert "description" in original["properties"]
        baseline["components"]["schemas"]["Example"]["properties"]["description"][
            "title"
        ] = "New"
        assert original == module.contract_shape(
            {"$ref": "#/components/schemas/Example"}, baseline
        )
        baseline["components"]["schemas"]["Example"]["required"] = []
        assert original != module.contract_shape(
            {"$ref": "#/components/schemas/Example"}, baseline
        )
        print("OpenAPI ref/metadata/property-name/required checks OK")
