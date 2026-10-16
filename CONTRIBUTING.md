# Contributing

## Clean-room rule

modbus-studio is implemented from the public Modbus specifications:

- *MODBUS Application Protocol Specification V1.1b3*
- *MODBUS over Serial Line Specification and Implementation Guide V1.02*
- *MODBUS Messaging on TCP/IP Implementation Guide V1.0b*

Do not contribute code, decompiled logic, icons, screenshots, documentation text or UI
copy taken from proprietary Modbus tools. Matching a common workflow is fine; copying an
implementation or its assets is not.

## Reporting issues

Open an issue at <https://github.com/electrolabopen/modbus-studio/issues>. For a protocol problem, include the device, the
connection type and the TX/RX frames from the traffic monitor.

## Development setup

```bash
git clone https://github.com/electrolabopen/modbus-studio.git && cd modbus-studio
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cd ../frontend && npm install
```

## Checks (the same ones CI runs)

```bash
# backend/
ruff check . && ruff format --check . && mypy && pytest -q
# frontend/
npm run lint && npm test && npm run build
```

Integration tests start the simulator in-process on free ports. They need no hardware
and no Docker.

## Guidelines

- Protocol behaviour lives in `backend/src/modbus_studio/core` and has no FastAPI
  imports. The API layer is a thin wrapper around it.
- Decoding happens in the backend only, so the UI, REST API and exporters always agree.
- Write tests against reference values derived by hand from the spec, not values
  produced by the code under test.
- Use conventional commit messages (`feat:`, `fix:`, `docs:`…).
- Open pull requests against `main` on <https://github.com/electrolabopen/modbus-studio>; CI must be green.
