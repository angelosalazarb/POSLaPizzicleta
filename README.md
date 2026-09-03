# POS La Pizzicleta — caja ligera con tickets 80mm

Sistema de facturación sencillo para la sede sur mientras llega el POS definitivo.
Servidor web local en el Mac; se accede desde el PC de caja por el navegador y los
tickets se imprimen en la térmica SAT (papel POS80) desde Chrome.

Tipografía: títulos en Pirata One; el cuerpo va en **Century Gothic** (usa la del
sistema; si el equipo no la tiene carga TeX Gyre Adventor autohospedada, un clon
libre); precios y tickets térmicos en IBM Plex Mono para que las cifras alineen.

- Facturas como **pestañas** ("cuentas"): cantidad × ítem × precio, texto libre.
- **Autocompletado desde la carta**: al escribir el ítem sugiere los productos del
  menú de niceeat (nombre, categoría y precio) y al elegir uno llena el precio solo.
  El catálogo vive en `data/menu.json` (productos scrapeados de
  lapizzicleta.niceeat.co); es un JSON editable a mano si cambian
  precios o hay productos nuevos.
- **Sabores y acompañantes de los combos**: al tocar un producto que en niceeat
  pide opciones (combos, pizza mitad y mitad, slices) se abre un modal igual al
  de la carta: sabores obligatorios ("Elige 2 sabores" exige exactamente 2, con
  buscador), adiciones con precio (máx. 4, se suman al valor del ítem), gaseosa
  del combo obligatoria y caja para llevar. Lo elegido queda en la descripción
  del ítem entre paréntesis y sale en el ticket y la comanda. Las reglas y
  opciones viven en `data/modificadores.json`, generado con
  `python3 data/generar-modificadores.py` desde la carta scrapeada
  (`data/carta-niceeat-completa.json`), que también anota en `menu.json` qué
  producto usa qué grupos.
- **Canal obligatorio en todo pedido**: cada cuenta debe decir si es en mesa,
  para llevar o domicilio (selector arriba, resaltado mientras falte); no deja
  cobrar ni enviar a cocina sin elegirlo. El botón **Nueva cuenta** lo pregunta
  de una vez en un modal: Para llevar / Domicilio como botones grandes y las
  mesas en un desplegable con **solo las disponibles** (sin cuentas activas).
- **Confirmación del pedido con el cliente**: si hay ítems nuevos sin confirmar
  (primera creación o productos agregados después), volver al tablero, "A
  cocina" y "Cobrar e imprimir" abren un modal con los ítems y valores — lo
  nuevo marcado con badge "nuevo" / "+N nuevo" — y el botón **Confirmar pedido**
  continúa con la acción ("Seguir editando" se queda). Sin cambios no vuelve a
  preguntar.
- **Pedido agregado a cuenta ya entregada**: marcar "Entregado" pone el chulito
  a todos los ítems; si después llega un ítem nuevo (sin chulito), la cuenta
  **vuelve sola a "En cocina"** y la comanda imprime **solo lo pendiente** con
  el banner "— ADICIÓN AL PEDIDO —" (si todo está entregado, la reimpresión
  sale completa).
- **Descuento** por cuenta en $ o %, el total nunca baja de 0. **Propina**
  en % (típico 10) o $ fijo. **Método de pago** (Efectivo / Datáfono / Nequi /
  **Transf. Bold** / **Transf. Bancolombia**, Efectivo por defecto): las
  transferencias se piden por cuenta de destino porque el QR de Bold cae en Bold
  (junto con el datáfono) y el resto en Bancolombia — sin esa separación el
  cierre no se puede cuadrar contra cada cuenta. El método viejo
  "Transferencia" se sigue aceptando en las cuentas ya cobradas y cuenta como
  Bancolombia; aparece en filtros y desglose solo en los días que lo usaron.
  Los tres viven como controles
  permanentes en el panel lateral mientras se arma el pedido (auto-guardado) —
  sale en el ticket, el export CSV y el desglose de "Ventas de hoy".
- **Modal de cobro**: al tocar "Cobrar e imprimir" se abre un modal de
  confirmación (además del panel, no en su lugar — escribe sobre los mismos
  campos de la cuenta, así que ambas superficies quedan siempre sincronizadas)
  con método de pago en grilla, propina por pills (Sin propina / 10% / Otro $)
  y descuento, más los totales en vivo. Con **Efectivo** aparece el ícono de
  vuelto (💵) que reabre la **calculadora de vuelto** existente: "La cuenta
  vale" → "Va a pagar" (lo que decide el cliente; la propina es la diferencia)
  → billetes rápidos → "El cliente entrega" → devuelta calculada. Al cerrar
  esa calculadora, la propina vuelve al modal de cobro ya actualizada.
- Todo se guarda solo (SQLite en `data/pos.db`): las pestañas sobreviven refrescos
  y se ven igual desde el Mac y desde el PC de caja.
- Vista **Ventas de hoy** organizada en tres sub-pestañas con el filtro de fecha
  compartido: **Ventas** (lista del día con **chips de filtro por método de pago
  y por mesa/canal** — muestra el total filtrado aparte del total del día —,
  propinas y desglose), **Caja** (retiros y pagos + cierre de caja con apertura)
  y **Auditoría** (cuadres de turno, log de excepciones con contador en la
  pestaña, y **export CSV** por rango de fechas, compatible con Excel para el
  consolidado TERRA).
- **Cierre de caja** (al final de Ventas de hoy): se digita la base de inicio y
  lo contado en efectivo, datáfono, **Transf. Bold (QR)** y **Transf.
  Bancolombia + Nequi** — una casilla por cuenta, que es como se cuadra contra
  la app de Bold y la del banco por separado; el botón
  de billete junto al campo de efectivo abre el **conteo por denominaciones**
  (billetes $2.000–$100.000 y monedas $50–$1.000): se pone la cantidad de cada
  una, muestra subtotales y el total, y "Usar total" llena el campo; el conteo
  se guarda junto con el cierre; compara en
  vivo contra lo registrado por el POS (con propinas), marca por rubro si
  "cuadra", falta (rojo) o sobra (naranja), calcula el total final del día sin
  la base, y **Guardar cierre** deja el registro del día en la base de datos
  (uno por fecha; volver a guardar lo actualiza).
- **Resumen del cierre** (modal al guardar): además de lo contado y el reparto
  de la plata, trae **dos tablas de venta/propina por método**. La primera,
  *Lo que se recibió según el POS*, es la clasificación que marcó la caja. La
  segunda, *Para la contabilidad (sobre lo contado)*, se arma con la plata que
  de verdad entró: `venta = entró − propina`, donde `entró` es el efectivo
  contado sin la base más las salidas, el datáfono contado y las transferencias
  contadas. **Esa segunda tabla es la que se asienta en el libro** — el desglose
  de propinas es exacto (el POS las guarda por factura) y la venta es el resto.
  Las filas son una por cuenta de destino: Efectivo, Datáfono, Transf. Bold y
  Transf. Banco + Nequi, que mapean 1:1 a Caja local, Bold, Bold y Bancolombia.
  Cuando las dos tablas no coinciden en la venta aparece un aviso: significa que
  alguna cuenta se cobró por un medio y quedó marcada por otro, típico de
  reaperturas con cambio de método. El aviso sale solo cuando los desvíos por
  método se cancelan entre sí (un cruce real) y no por un descuadre pequeño.
- **Corregir una cuenta ya cobrada**: el botón de lápiz en Ventas de hoy la
  reabre como pestaña (sale del total del día mientras tanto), se edita lo que
  sea (ítems, descuento, propina, método) y se vuelve a cobrar con el mismo
  número de cuenta.
- **Cierre ciego** (práctica antifraude estándar de la industria): mientras el
  día no tenga cierre guardado, el formulario de cierre, el cuadre de turno y el
  desglose por método muestran `•••` en vez de lo esperado — se cuenta la plata
  sin saber contra qué se compara. Al **guardar** se revela la comparación
  completa (modal de resumen) y el **primer conteo queda congelado** en la base;
  si después se corrige el cierre, junto al botón queda visible "corregido tras
  el conteo ciego de las HH:MM (era $X)" y la corrección va al log de
  excepciones. Se apaga con `CIERRE_CIEGO = False` en `app.py`.
- **Log de excepciones** (append-only, sin endpoint para editarlo ni borrarlo):
  toda **anulación**, **reapertura** y **eliminación de salida** exige un motivo
  (modal con atajos de un toque + texto libre; el servidor rechaza la acción sin
  motivo), y el sistema registra solo los **descuentos cobrados**, las
  **correcciones de cierre** y los **cambios de base de la apertura**. La
  sección "Excepciones del día" en Ventas lista hora, tipo, cuenta/referencia,
  motivo y monto de cada evento — la primera fuente al investigar un descuadre.

> **¿Correrlo en el computador de la pizzería (Windows)?** Guía completa en
> **[SETUP-PIZZERIA.md](SETUP-PIZZERIA.md)** — instalación de Python, `run-windows.bat`,
> arranque automático, firewall, respaldos. Regla: el servidor corre en UN solo
> equipo a la vez (la base de ventas es `data/pos.db`).

## Arranque (en este Mac)

```bash
cd "projects/lapizzicleta/pos"
uv run --with flask app.py
```

Queda sirviendo en `http://0.0.0.0:8085`. En este Mac: <http://localhost:8085>.

## Acceso desde el PC de caja

1. Averiguar la IP del Mac en la red del local:

   ```bash
   ipconfig getifaddr en0   # WiFi; si el cable va por adaptador probar en1..en5
   ```

2. En el PC de caja abrir Chrome → `http://<IP-del-Mac>:8085`.
3. Si no carga: en el Mac, **Configuración del Sistema → Red → Firewall** —
   permitir conexiones entrantes a Python (o desactivar el firewall en la red local).
4. Recomendado: fijar la IP del Mac (reservación DHCP en el router o IP manual)
   para que el marcador del PC de caja no se dañe cuando cambie la IP.

## Impresora SAT POS80 (en el PC de caja)

La impresión sale del navegador del PC de caja, donde está la SAT por USB:

1. Instalar/verificar el **driver SAT** y que imprima una página de prueba de Windows.
2. En el driver, dejar el tamaño de papel en **POS80 / 80(72.1) × 297mm / Receipt**.
3. En Chrome, al imprimir el ticket:
   - Destino: la SAT · Tamaño de papel: POS80 · **Márgenes: Ninguno** ·
     Escala: 100% · Sin encabezados ni pies de página.
   - Chrome recuerda estas opciones para las próximas impresiones.
4. El botón **Cobrar e imprimir** abre el ticket (`/ticket/<id>?print=1`) y lanza
   el diálogo de impresión solo; con Enter sale el ticket.
5. **Impresión silenciosa (opcional):** crear un acceso directo de Chrome con
   `--kiosk-printing` y usar ese Chrome solo para la caja — imprime directo en la
   predeterminada sin diálogo. Poner la SAT como impresora predeterminada de Windows.

## Estructura

```
pos/
├── app.py              # Flask: API + frontend + ticket (puerto 8085)
├── pos.html            # interfaz de caja (un solo archivo)
├── static/
│   ├── logo.png        # sticker a color (512px)
│   ├── logo-ticket.png # sticker B/N para la térmica
│   └── fonts/          # Pirata One (títulos), TeX Gyre Adventor (respaldo libre de
│                       # Century Gothic para el cuerpo), Archivo, IBM Plex Mono — sin internet
└── data/pos.db         # base SQLite (respaldar este archivo = respaldar las ventas)
```

## API (por si hace falta integrar algo después)

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/api/menu` | catálogo de la carta (`data/menu.json`) para el autocompletado |
| GET | `/api/modificadores` | grupos de sabores/acompañantes (`data/modificadores.json`) |
| GET | `/api/facturas?estado=abierta` | cuentas abiertas con sus ítems |
| POST | `/api/facturas` | nueva cuenta (numeración F-001 reinicia cada día) |
| PUT | `/api/facturas/<id>` | guardar ítems + descuento + nota |
| POST | `/api/facturas/<id>/cerrar` · `/anular` · `/reabrir` | cerrar, anular, o reabrir una cerrada/anulada para editarla (anular y reabrir exigen `{"motivo": "..."}`) |
| GET | `/api/excepciones?fecha=` | log append-only del día: anulaciones, reaperturas, descuentos, salidas eliminadas, correcciones |
| GET | `/api/ventas?fecha=YYYY-MM-DD` | cerradas del día + total |
| GET | `/api/export?desde=&hasta=` | CSV del rango (una fila por ítem) |
| GET/POST | `/api/cierre?fecha=` | cierre de caja del día (el GET omite los esperados mientras el cierre ciego esté activo y el día sin guardar) |
| GET | `/api/backup` | descarga una copia consistente de `pos.db` (respaldo o migración de equipo) |
| GET | `/ticket/<id>?print=1` | ticket 80mm; `print=1` lanza la impresión |

Los totales los calcula el servidor al guardar (fuente de verdad); el navegador
solo los muestra en vivo.

## Respaldo

Todo vive en `data/pos.db`. Abrir `/api/backup` en el navegador descarga una
copia consistente ya fechada (también sirve copiar el archivo directamente); el
export CSV sirve para contabilidad pero no reemplaza el respaldo.

## Repositorio

Código sincronizado en <https://github.com/angelosalazarb/POSLaPizzicleta>.
La base `data/pos.db` está excluida del repo a propósito (datos del negocio):
se mueve entre equipos con `/api/backup`. En Windows, `actualizar-windows.bat`
hace el `git pull`.
