# modbus-studio

An open-source Modbus master that runs in your browser. It polls Modbus TCP, RTU and
RTU-over-TCP devices, decodes their registers into engineering values, writes coils and
registers, and shows every frame on the wire. Run it on your laptop, or on a gateway or
Raspberry Pi on the plant network and open it from any browser.

![modbus-studio in use](https://raw.githubusercontent.com/electrolabopen/modbus-studio/main/docs/screenshots/demo.gif)

## Install and run

```bash
pipx install modbus-studio      # or: pip install modbus-studio
modbus-studio                   # open http://127.0.0.1:8000
```

The package includes the web UI; no Node.js is needed. A slave simulator comes with it,
to try everything without hardware:

```bash
modbus-studio-sim               # Modbus TCP on :5020, RTU over TCP on :5021
```

Then, in the UI, **+ Connection** → Modbus TCP, `127.0.0.1`, port `5020`, and
**+ Window**. Serial ports (RTU) are listed in the connection dialog.

## What it does

- Modbus TCP, RTU over TCP and RTU on a serial port; FC01–FC04 reads, FC05/06/15/16 writes.
- 16, 32 and 64-bit integers and floats in the four byte orders, scale and unit per
  register, aliases, CSV register maps.
- Several polling windows with their own scan rates, a traffic monitor with the raw
  frames, a real-time chart, writes with a confirmation dialog and a write log.
- Export to InfluxDB 2.x and publishing over MQTT, configured from the UI.
- REST API and WebSocket (OpenAPI at `/docs`), JSON workspaces saved automatically.

## On a network

The server listens on `127.0.0.1` only. To open it to other machines, set a token:

```bash
MODBUS_STUDIO_HOST=0.0.0.0 MODBUS_STUDIO_TOKEN="$(openssl rand -hex 24)" modbus-studio
```

Anyone who can reach the API can write to your devices: do not expose it without a
token, and preferably keep it behind a VPN or a reverse proxy with TLS.
`modbus-studio --help` lists the settings.

## More

Documentation, the Docker image (`ghcr.io/electrolabopen/modbus-studio`, amd64 and
arm64), the changelog and the issue tracker: <https://github.com/electrolabopen/modbus-studio>
([español](https://github.com/electrolabopen/modbus-studio/blob/main/README.es.md)).

MIT licensed. modbus-studio is an independent project, not affiliated with, endorsed by
or sponsored by Witte Software. "Modbus" is a trademark of Schneider Electric USA, Inc.
