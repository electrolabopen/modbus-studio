# modbus-studio

[![CI](https://github.com/electrolabopen/modbus-studio/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/electrolabopen/modbus-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Container image](https://img.shields.io/badge/image-ghcr.io-2496ED?logo=docker&logoColor=white)](https://github.com/electrolabopen/modbus-studio/pkgs/container/modbus-studio)

[English](README.md) · **Español**

Un maestro Modbus de código abierto que funciona en el navegador. Sondea equipos Modbus
TCP, RTU y RTU sobre TCP, convierte sus registros en valores de ingeniería, escribe
bobinas y registros, y muestra cada trama que pasa por la línea. Está escrito desde cero
a partir de la especificación pública de Modbus. Se puede usar en un portátil, o en un
gateway o una Raspberry Pi en la red de planta y abrirlo desde cualquier navegador.

![modbus-studio en uso: una ventana de sondeo, la gráfica en tiempo real, el monitor de tráfico y los exportadores](docs/screenshots/demo.gif)

> **Estado: pre-alfa, versión 0.1.0.** Todo lo que aparece en [Funciona hoy](#funciona-hoy)
> está terminado y probado; lo que falta está [en desarrollo](#en-desarrollo). Ver la
> [hoja de ruta](docs/ROADMAP.md) y el [registro de cambios](CHANGELOG.md) (en inglés).

La interfaz y la documentación detallada están en inglés; este archivo resume lo esencial
en español.

## Funcionalidades

### Funciona hoy

| Área | Qué funciona |
|---|---|
| Protocolos | Modbus TCP, RTU sobre TCP y RTU por puerto serie: detección de puertos y parámetros de línea en la UI ([guía para Linux](docs/rtu-linux.md)) |
| Funciones | Lectura FC01–FC04, escritura FC05/06/15/16 |
| Decodificación | con signo, sin signo, hex, binario, long/float de 32 bits, long/double de 64 bits; órdenes de bytes ABCD, CDAB, BADC, DCBA; escala y unidad por registro (valores de ingeniería) |
| Ventanas de sondeo | Varias ventanas, cada una con su conexión, ID de esclavo, función y periodo de sondeo; contadores Tx/Err |
| Formatos y alias | Formato por celda o por rango, alias editables en la tabla, mapas de registros en CSV |
| Escrituras | Doble clic en una celda, diálogo de confirmación, valores en unidades de ingeniería, registro de escrituras; conexiones de solo lectura |
| Workspaces | Workspaces JSON con guardado automático, importación y exportación |
| Monitor de tráfico | Tramas TX/RX en crudo con filtros, pausa, contadores y exportación a CSV |
| Gráfica | Gráfica en tiempo real de los registros seleccionados (uPlot), pausa, zoom, exportación a CSV |
| InfluxDB | Exportación a InfluxDB 2.x, perfil de compose con Grafana y un dashboard para el simulador ([guía](docs/influxdb.md)) |
| MQTT | Publica cada valor como JSON (valor, unidad, marca de tiempo) en un topic configurable, QoS 0/1/2, retain, TLS; perfil de compose con Mosquitto ([guía](docs/mqtt.md)) |
| Configuración de exportadores | InfluxDB y MQTT se configuran desde la UI, con estado en vivo, contadores y prueba de conexión; los tokens y contraseñas se escriben pero nunca se muestran |
| API | API REST + WebSocket, la misma que usa la UI; OpenAPI en `/docs` |
| Seguridad | Escucha en 127.0.0.1 por defecto, token de API opcional |
| Docker | `docker compose up` con el simulador incluido |
| Teléfonos y tablets | En pantallas angostas la barra de herramientas pasa a un menú, así que la UI se puede usar desde el teléfono en planta |

### En desarrollo

| Funcionalidad | Dónde |
|---|---|
| RTU con un adaptador USB-RS485 físico: por ahora solo probado con puertos virtuales | 0.2.0 (fase 6, parte 3) |
| Una Raspberry Pi 4/5 física: por ahora la imagen arm64 se prueba en los runners arm64 de GitHub y bajo QEMU | 0.2.0 |

La [hoja de ruta](docs/ROADMAP.md) detalla las fases y lo que cada una debe cumplir.

## Capturas

Una ventana de sondeo con el mapa de registros del simulador aplicado, y la gráfica en
tiempo real de dos de sus registros:

![Ventana de sondeo y gráfica](docs/screenshots/window-chart.jpg)

El monitor de tráfico, con cada petición y respuesta en hexadecimal:

![Monitor de tráfico](docs/screenshots/window-traffic.jpg)

El diálogo de exportadores: configuración de InfluxDB y MQTT, estado en vivo y prueba de
conexión:

![Diálogo de exportadores](docs/screenshots/exporters.jpg)

Los mismos valores en Grafana, exportados a InfluxDB (`docker compose --profile influxdb up`):

![Dashboard de Grafana](docs/screenshots/grafana-dashboard.jpg)

## Inicio rápido

### Docker (aplicación + simulador)

```bash
git clone https://github.com/electrolabopen/modbus-studio.git
cd modbus-studio
docker compose up --build
```

Después abre <http://127.0.0.1:8000>. Una conexión al simulador incluido y una ventana
de demostración se cargan desde [`docker/demo-workspace.json`](docker/demo-workspace.json),
así que los valores se actualizan desde el primer momento.

El host que hay que usar depende de dónde corre el maestro Modbus:

| Maestro | Host | Puerto |
|---|---|---|
| modbus-studio dentro de compose | `simulator` (nombre del servicio) | 5020 TCP, 5021 RTU sobre TCP |
| Cualquier herramienta en el PC anfitrión | `127.0.0.1` | 5020 TCP, 5021 RTU sobre TCP |

Las conexiones y ventanas se guardan en el volumen `modbus-studio-data` tras cada cambio
y se restauran cuando el contenedor se reinicia o se recrea. El workspace de demostración
solo se usa en el primer arranque, así que una conexión de demostración que borres sigue
borrada. Para empezar de nuevo desde la demostración, elimina el volumen con
`docker compose down -v`.

Dentro del contenedor de la aplicación, `127.0.0.1` es el propio contenedor, así que una
conexión a `127.0.0.1:5020` creada desde la UI falla; la barra lateral explica por qué.
Para comprobar el stack:

```bash
docker compose up -d --build --wait
python docker/smoke_test.py      # aplicación -> simulador por la red de compose
# el workspace sobrevive a que se mate el contenedor de la aplicación:
python docker/smoke_test.py persist-write
docker compose kill modbus-studio && docker compose up -d --wait
python docker/smoke_test.py persist-check
```

### Con InfluxDB y Grafana

```bash
docker compose --profile influxdb up --build
```

añade InfluxDB 2 y Grafana: los valores sondeados se exportan a InfluxDB y Grafana
(<http://127.0.0.1:3000>) abre un dashboard para el simulador. Ver
[`docs/influxdb.md`](docs/influxdb.md).

### Con Mosquitto (MQTT)

```bash
docker compose --profile mqtt up --build
docker compose exec mosquitto mosquitto_sub -u modbus-studio -P modbus-studio -t 'modbus-studio/#' -v
```

añade Mosquitto, y cada valor sondeado se publica en él como JSON. Los dos perfiles
pueden ir juntos (`--profile influxdb --profile mqtt`). Ver [`docs/mqtt.md`](docs/mqtt.md).

Las contraseñas y el token de estos perfiles son **valores de desarrollo**: cámbialos
antes de exponer nada (ver las guías).

### Con pip

A partir de la 0.1.0, modbus-studio está en PyPI, con la UI incluida (no hace falta Node.js):

```bash
pipx install modbus-studio      # o: pip install modbus-studio
modbus-studio                   # http://127.0.0.1:8000
modbus-studio-sim               # opcional: el simulador de esclavo en :5020 / :5021
```

### Imagen Docker

Las imágenes multiarquitectura (`linux/amd64`, `linux/arm64`, así que también una
Raspberry Pi 4/5 con sistema de 64 bits) se publican en
[`ghcr.io/electrolabopen/modbus-studio`](https://github.com/electrolabopen/modbus-studio/pkgs/container/modbus-studio):

```bash
docker run -d --name modbus-studio -p 127.0.0.1:8000:8000 \
  -v modbus-studio-data:/data ghcr.io/electrolabopen/modbus-studio:edge
```

| Tag | |
|---|---|
| `edge` | el último commit de `main` que pasó el CI |
| `sha-<commit>` | un commit concreto de `main` |
| `0.1.0`, `0.1`, `latest` | versiones publicadas, a partir de la 0.1 |

La imagen escucha en el puerto 8000 dentro del contenedor; publícalo en `127.0.0.1` como
arriba, o lee [Uso en un gateway o en la red de planta](#uso-en-un-gateway-o-en-la-red-de-planta)
antes de abrirlo a la red. El workspace y el registro de escrituras viven en `/data`. Para
un adaptador USB-RS485 añade `--device /dev/ttyUSB0` ([`docs/rtu-linux.md`](docs/rtu-linux.md)).

### Desde el código fuente

Requiere Python ≥ 3.10 y Node ≥ 20.

```bash
git clone https://github.com/electrolabopen/modbus-studio.git
cd modbus-studio

# backend
cd backend
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
modbus-studio-sim &             # simulador de esclavo en :5020 / :5021
modbus-studio                   # API en http://127.0.0.1:8000

# frontend (servidor de desarrollo con recarga en caliente, redirige /api al backend)
cd ../frontend
npm install
npm run dev                     # http://127.0.0.1:5173
```

`npm run build` compila la UI en `backend/src/modbus_studio/static`, y el servidor de
Python la sirve en su propio puerto.

## Uso en un gateway o en la red de planta

Por defecto el servidor solo escucha en `127.0.0.1`. Para acceder desde otras máquinas:

```bash
export MODBUS_STUDIO_HOST=0.0.0.0
export MODBUS_STUDIO_TOKEN="$(openssl rand -hex 24)"
modbus-studio
```

Con un token configurado, cada llamada a la API debe enviar `Authorization: Bearer <token>`.
**Cualquiera que llegue a la API puede escribir en tus equipos.** No la expongas sin
token y, preferiblemente, mantenla detrás de una VPN o de un proxy inverso con TLS.

| Variable | Por defecto | Uso |
|---|---|---|
| `MODBUS_STUDIO_HOST` | `127.0.0.1` | Dirección de escucha |
| `MODBUS_STUDIO_PORT` | `8000` | Puerto HTTP |
| `MODBUS_STUDIO_TOKEN` | *(sin definir)* | Exigir este token bearer en la API |
| `MODBUS_STUDIO_TRAFFIC_BUFFER` | `5000` | Tramas que guarda el monitor de tráfico |
| `MODBUS_STUDIO_WORKSPACE` | *(sin definir)* | Workspace JSON con conexiones y ventanas que se carga al arrancar |
| `MODBUS_STUDIO_WRITE_LOG_FILE` | *(sin definir; `/data/writes.jsonl` en Docker)* | Añade cada escritura a este archivo JSON Lines |
| `MODBUS_STUDIO_STATE_FILE` | *(sin definir; `/data/workspace.json` en Docker)* | Guarda aquí el workspace tras cada cambio y lo restaura al arrancar; cuando existe, tiene prioridad sobre `MODBUS_STUDIO_WORKSPACE` |

## Workspaces, mapas de registros y registro de escrituras

- **Workspaces.** Las conexiones, ventanas, formatos y alias se guardan tras cada cambio
  (en Docker: `/data/workspace.json`) y se restauran al arrancar. **Export workspace**
  descarga la sesión como JSON; **Import workspace…** carga uno, reemplazando la sesión
  o añadiéndolo a ella.
- **Mapas de registros en CSV.** **Import CSV map…** en una ventana aplica un archivo con
  las columnas `address,alias,type,byte_order,scale,unit` (solo `address` es obligatoria,
  separadas por `,` o `;`). Primero se comprueba cada fila y los problemas se listan por
  línea; no se aplica nada hasta que todo el archivo es válido. Las direcciones son
  direcciones de protocolo empezando en 0.
  [`docs/examples/simulator-map.csv`](docs/examples/simulator-map.csv) describe el
  simulador incluido: impórtalo en una ventana FC03 con dirección 0 y cantidad 28.
- **Registro de escrituras.** Cada escritura enviada desde la UI o la API se registra con
  la hora, la conexión, el equipo, la función, la dirección, el valor mostrado antes y el
  nuevo, incluidas las que el equipo rechazó. **Write log** en la barra de herramientas
  lo muestra; se guarda en `/data/writes.jsonl` (`MODBUS_STUDIO_WRITE_LOG_FILE` fuera de
  Docker).

## Modbus RTU por puerto serie

Elige **Modbus RTU (serial port)** en **+ Connection**: el diálogo lista los puertos
serie de la máquina donde corre el servidor. [`docs/rtu-linux.md`](docs/rtu-linux.md)
cubre los adaptadores USB-RS485 en Linux (`dialout`, reglas udev, `/dev/serial/by-id`,
`--device` en Docker, cableado) y cómo probar RTU sin hardware: con socat en Linux, o
com0com en Windows.

El simulador también puede ser un esclavo RTU en un puerto serie:

```bash
modbus-studio-sim --serial /dev/ttyUSB0                 # 19200 8E1, además de los puertos TCP
modbus-studio-sim --tcp-port 0 --rtu-tcp-port 0 --serial COM10 --baudrate 9600 --parity N
```

## Mapa de registros del simulador

`modbus-studio-sim` atiende los ID de equipo 1 y 2. Los holding registers y los input
registers comparten esta distribución (direcciones de protocolo empezando en 0):

| Dirección | Tipo | Contenido |
|---|---|---|
| 0 | uint16 | contador, +1 por segundo |
| 1 | uint16 | diente de sierra 0–100, periodo de 10 s |
| 2 | int16 | temperatura ×10, −50,0 … 150,0 °C (usar escala 0,1) |
| 10–11 / 12–13 / 14–15 / 16–17 | float32 | la misma senoide en ABCD / CDAB / BADC / DCBA |
| 20–23 | float64 | la misma senoide, ABCD |
| 24–25 | int32 | −123456789, ABCD |
| 26–27 | uint32 | 3000000000, CDAB |
| 100–199 | — | libres, escribibles |

Hay 100 bobinas escribibles (0–99). Las entradas discretas 0–15 muestran un bit que se
desplaza una posición por segundo.

## Nombres de los órdenes de bytes

`A` es el byte más significativo de un valor de 32 bits:

| Nombre | Registros | También llamado |
|---|---|---|
| ABCD | `[AB, CD]` | big-endian |
| CDAB | `[CD, AB]` | word swap / orden de palabras little-endian |
| BADC | `[BA, DC]` | byte swap |
| DCBA | `[DC, BA]` | little-endian |

Para valores de 64 bits se aplican las mismas dos operaciones a las cuatro palabras.

## Documentación

Las guías están en inglés.

| Guía | |
|---|---|
| [`docs/rtu-linux.md`](docs/rtu-linux.md) | Adaptadores USB-RS485 en Linux, udev, `--device` en Docker, cableado; RTU sin hardware (socat, com0com) |
| [`docs/influxdb.md`](docs/influxdb.md) | Exportador de InfluxDB: qué se escribe, ajustes, buffer, Grafana, credenciales |
| [`docs/mqtt.md`](docs/mqtt.md) | Exportador MQTT: topics, payload JSON, QoS, TLS, Mosquitto |
| [`docs/examples/simulator-map.csv`](docs/examples/simulator-map.csv) | Mapa de registros en CSV del simulador incluido |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Fases, lo que cada una debe cumplir, notas de diseño |
| [`docs/releasing.md`](docs/releasing.md) | Publicación de la imagen y de versiones (mantenedores) |
| [`CHANGELOG.md`](CHANGELOG.md) | Cambios por versión |
| `http://127.0.0.1:8000/docs` | La API REST (OpenAPI), servida por la propia aplicación |

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md) (en inglés). Los errores y las peticiones de
funcionalidades van al [gestor de incidencias](https://github.com/electrolabopen/modbus-studio/issues).
Es un proyecto de sala limpia (clean-room): por favor, no contribuyas código, capturas,
iconos ni textos tomados de herramientas Modbus propietarias.

## Licencia y aviso legal

MIT, ver [LICENSE](LICENSE).

modbus-studio es un proyecto independiente. **No está afiliado a Witte Software, ni
cuenta con su respaldo o patrocinio.** "Modbus" es una marca registrada de Schneider
Electric USA, Inc.; las especificaciones del protocolo las publica la Modbus
Organization en <https://modbus.org>.
