#!/usr/bin/env python3
"""POS ligero La Pizzicleta — servidor local con tickets 80mm.

Arranque:  uv run --with flask app.py
Acceso desde caja:  http://<IP-del-Mac>:8085
"""

import csv
import html
import io
import json
import os
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, request, send_file, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
# POS_DB / POS_PORT: solo para entornos de prueba; producción no define nada
DB_PATH = Path(os.environ.get("POS_DB", BASE_DIR / "data" / "pos.db"))
POS_HTML = BASE_DIR / "pos.html"
MENU_JSON = BASE_DIR / "data" / "menu.json"
MODIFICADORES_JSON = BASE_DIR / "data" / "modificadores.json"

app = Flask(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_dia INTEGER NOT NULL,
    fecha_apertura TEXT NOT NULL,
    fecha_cierre TEXT,
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta','cerrada','anulada')),
    descuento_tipo TEXT NOT NULL DEFAULT 'monto' CHECK (descuento_tipo IN ('monto','porcentaje')),
    descuento_valor REAL NOT NULL DEFAULT 0,
    subtotal INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    nota TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    factura_id INTEGER NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
    cantidad REAL NOT NULL DEFAULT 1,
    descripcion TEXT NOT NULL DEFAULT '',
    precio_unitario INTEGER NOT NULL DEFAULT 0,
    subtotal INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_factura ON items(factura_id);
CREATE INDEX IF NOT EXISTS idx_facturas_fecha ON facturas(fecha_apertura);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'Retiro',
    concepto TEXT NOT NULL DEFAULT '',
    monto INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos(fecha);
CREATE TABLE IF NOT EXISTS aperturas (
    fecha TEXT PRIMARY KEY,
    base INTEGER NOT NULL DEFAULT 0,
    conteo_efectivo TEXT NOT NULL DEFAULT '',
    guardado_en TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cuadres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    base INTEGER NOT NULL DEFAULT 0,
    efectivo_contado INTEGER NOT NULL DEFAULT 0,
    transferencias_contado INTEGER NOT NULL DEFAULT 0,
    esperado_efectivo INTEGER NOT NULL DEFAULT 0,
    esperado_transferencias INTEGER NOT NULL DEFAULT 0,
    dif_efectivo INTEGER NOT NULL DEFAULT 0,
    dif_transferencias INTEGER NOT NULL DEFAULT 0,
    conteo_efectivo TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cuadres_fecha ON cuadres(fecha);
CREATE TABLE IF NOT EXISTS mesas (
    nombre TEXT PRIMARY KEY,
    orden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cierres (
    fecha TEXT PRIMARY KEY,
    base INTEGER NOT NULL DEFAULT 0,
    efectivo_contado INTEGER NOT NULL DEFAULT 0,
    datafono_contado INTEGER NOT NULL DEFAULT 0,
    transferencias_contado INTEGER NOT NULL DEFAULT 0,
    esperado_efectivo INTEGER NOT NULL DEFAULT 0,
    esperado_datafono INTEGER NOT NULL DEFAULT 0,
    esperado_transferencias INTEGER NOT NULL DEFAULT 0,
    total_final INTEGER NOT NULL DEFAULT 0,
    diferencia INTEGER NOT NULL DEFAULT 0,
    guardado_en TEXT NOT NULL,
    conteo_efectivo TEXT NOT NULL DEFAULT ''
);
"""


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


MIGRACIONES = [
    "ALTER TABLE facturas ADD COLUMN propina_tipo TEXT NOT NULL DEFAULT 'porcentaje'",
    "ALTER TABLE facturas ADD COLUMN propina_valor REAL NOT NULL DEFAULT 0",
    "ALTER TABLE facturas ADD COLUMN propina INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE facturas ADD COLUMN metodo_pago TEXT NOT NULL DEFAULT 'Efectivo'",
    "ALTER TABLE facturas ADD COLUMN reabierta INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE cierres ADD COLUMN conteo_efectivo TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE cierres ADD COLUMN salidas INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE facturas ADD COLUMN etapa TEXT NOT NULL DEFAULT 'en_progreso'",
    "ALTER TABLE facturas ADD COLUMN fecha_enviada TEXT",
    "ALTER TABLE facturas ADD COLUMN fecha_entregada TEXT",
    "ALTER TABLE facturas ADD COLUMN mesa TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE movimientos ADD COLUMN origen TEXT NOT NULL DEFAULT 'Efectivo'",
    "ALTER TABLE cierres ADD COLUMN base_siguiente INTEGER",
    "ALTER TABLE cierres ADD COLUMN conteo_base_siguiente TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE facturas ADD COLUMN archivada INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE items ADD COLUMN entregado INTEGER NOT NULL DEFAULT 0",
]

METODOS_PAGO = ("Efectivo", "Datáfono", "Nequi", "Transferencia")
TIPOS_MOVIMIENTO = ("Retiro", "Pago proveedor", "Gasto", "Propinas")
ORIGENES_MOVIMIENTO = ("Efectivo", "Transferencia")  # de dónde sale la plata

NUM_MESAS = 8              # solo la semilla inicial; las mesas se editan desde la UI
MESAS_FIJAS = ("Para llevar", "Domicilio")  # canales fijos, no son mesas editables
RETENCION_PAGADA_MIN = 10  # minutos que una cuenta pagada sigue visible en caja
SEMAFORO_MIN = [10, 18]    # verde < 10 min, amarillo 10–18, rojo > 18
# ciclo operativo de la cuenta; solo avanza, nunca retrocede
ETAPAS = ("en_progreso", "enviada", "entregada", "pagada")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)
        for sql in MIGRACIONES:
            try:
                db.execute(sql)
            except sqlite3.OperationalError:
                pass  # la columna ya existe
        # una cerrada es por definición pagada (facturas de antes de la columna etapa)
        db.execute("UPDATE facturas SET etapa='pagada'"
                   " WHERE estado='cerrada' AND etapa='en_progreso'")
        # semilla de mesas la primera vez; después se administran desde la UI
        if db.execute("SELECT COUNT(*) FROM mesas").fetchone()[0] == 0:
            for i in range(1, NUM_MESAS + 1):
                db.execute("INSERT INTO mesas (nombre, orden) VALUES (?, ?)",
                           (f"Mesa {i}", i))


def calcular_totales(items, descuento_tipo, descuento_valor,
                     propina_tipo="porcentaje", propina_valor=0):
    subtotal = sum(int(round(i["cantidad"] * i["precio_unitario"])) for i in items)
    if descuento_tipo == "porcentaje":
        descuento = int(round(subtotal * min(max(descuento_valor, 0), 100) / 100))
    else:
        descuento = int(min(max(descuento_valor, 0), subtotal))
    total = max(subtotal - descuento, 0)
    if propina_tipo == "porcentaje":
        propina = int(round(total * min(max(propina_valor, 0), 100) / 100))
    else:
        propina = int(max(propina_valor, 0))
    return subtotal, total, descuento, propina


def factura_dict(db, row):
    items = db.execute(
        "SELECT id, cantidad, descripcion, precio_unitario, subtotal, entregado"
        " FROM items WHERE factura_id = ? ORDER BY id", (row["id"],)
    ).fetchall()
    d = dict(row)
    d["items"] = [dict(i) for i in items]
    d["numero"] = f"F-{row['numero_dia']:03d}"
    d["total_pagar"] = d["total"] + d.get("propina", 0)
    return d


# ---------- frontend ----------

@app.get("/")
def index():
    return send_file(POS_HTML)


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(BASE_DIR / "static", name)


@app.get("/api/menu")
def menu():
    if not MENU_JSON.exists():
        return jsonify([])
    return send_file(MENU_JSON, mimetype="application/json")


@app.get("/api/modificadores")
def modificadores():
    """Grupos de modificadores (sabores de combo, adiciones, gaseosas...):
    {grupo: {obligatorio, min, max, opciones: [{nombre, precio}]}}."""
    if not MODIFICADORES_JSON.exists():
        return jsonify({})
    return send_file(MODIFICADORES_JSON, mimetype="application/json")


@app.get("/api/config")
def get_config():
    return jsonify({
        "num_mesas": NUM_MESAS,
        "retencion_pagada_min": RETENCION_PAGADA_MIN,
        "semaforo_min": SEMAFORO_MIN,
    })


# ---------- mesas configurables ----------

@app.get("/api/mesas")
def listar_mesas():
    db = get_db()
    rows = db.execute("SELECT nombre FROM mesas ORDER BY orden, nombre").fetchall()
    return jsonify({"mesas": [r["nombre"] for r in rows]})


@app.post("/api/mesas")
def crear_mesa():
    db = get_db()
    nombre = str((request.get_json(force=True) or {}).get("nombre") or "").strip()[:20]
    if not nombre:
        return jsonify({"error": "la mesa necesita un nombre"}), 400
    if nombre in MESAS_FIJAS:
        return jsonify({"error": f"«{nombre}» ya existe como opción fija"}), 409
    if db.execute("SELECT 1 FROM mesas WHERE nombre = ?", (nombre,)).fetchone():
        return jsonify({"error": f"la mesa «{nombre}» ya existe"}), 409
    orden = db.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS o FROM mesas").fetchone()["o"]
    db.execute("INSERT INTO mesas (nombre, orden) VALUES (?, ?)", (nombre, orden))
    db.commit()
    return listar_mesas(), 201


@app.delete("/api/mesas/<path:nombre>")
def eliminar_mesa(nombre):
    """Quita la mesa de la lista; las cuentas viejas conservan su rótulo."""
    db = get_db()
    nombre = nombre.strip()
    if db.execute("SELECT 1 FROM mesas WHERE nombre = ?", (nombre,)).fetchone() is None:
        return jsonify({"error": "esa mesa no existe"}), 404
    abiertas = db.execute(
        "SELECT COUNT(*) AS c FROM facturas WHERE estado='abierta' AND mesa = ?",
        (nombre,)).fetchone()["c"]
    if abiertas:
        return jsonify({"error": f"la mesa «{nombre}» tiene cuentas abiertas"}), 409
    db.execute("DELETE FROM mesas WHERE nombre = ?", (nombre,))
    db.commit()
    return listar_mesas()


# ---------- API facturas ----------

@app.get("/api/facturas")
def listar_facturas():
    db = get_db()
    estado = request.args.get("estado")
    if estado:
        rows = db.execute(
            "SELECT * FROM facturas WHERE estado = ? ORDER BY id", (estado,)
        ).fetchall()
    else:
        # vista de caja: abiertas + pagadas del día sin entregar (mostrador: pagan
        # primero) + pagadas-y-entregadas recientes (retención de unos minutos)
        limite = (datetime.now() - timedelta(minutes=RETENCION_PAGADA_MIN)
                  ).isoformat(timespec="seconds")
        hoy = date.today().isoformat()
        rows = db.execute(
            "SELECT * FROM facturas WHERE estado='abierta'"
            " OR (estado='cerrada' AND archivada=0 AND ("
            "   (etapa NOT IN ('entregada','pagada') AND date(fecha_cierre) >= ?)"
            "   OR COALESCE(MAX(fecha_entregada, fecha_cierre), fecha_cierre) >= ?"
            " )) ORDER BY id",
            (hoy, limite),
        ).fetchall()
    return jsonify([factura_dict(db, r) for r in rows])


@app.post("/api/facturas")
def crear_factura():
    db = get_db()
    # consecutivo continuo: nunca reinicia (numero_dia guarda el consecutivo global)
    n = db.execute(
        "SELECT COALESCE(MAX(numero_dia), 0) + 1 AS n FROM facturas"
    ).fetchone()["n"]
    cur = db.execute(
        "INSERT INTO facturas (numero_dia, fecha_apertura) VALUES (?, ?)",
        (n, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(factura_dict(db, row)), 201


@app.put("/api/facturas/<int:fid>")
def guardar_factura(fid):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    if row["estado"] != "abierta":
        return jsonify({"error": "la factura ya no está abierta"}), 409

    data = request.get_json(force=True)
    items_in = []
    for i in data.get("items", []):
        try:
            cantidad = max(float(i.get("cantidad") or 0), 0)
            precio = max(int(i.get("precio_unitario") or 0), 0)
        except (TypeError, ValueError):
            continue
        desc = str(i.get("descripcion") or "").strip()
        if not desc and cantidad == 0 and precio == 0:
            continue
        items_in.append({
            "cantidad": cantidad, "descripcion": desc, "precio_unitario": precio,
            "entregado": 1 if i.get("entregado") else 0,
        })

    descuento_tipo = data.get("descuento_tipo", "monto")
    if descuento_tipo not in ("monto", "porcentaje"):
        descuento_tipo = "monto"
    try:
        descuento_valor = max(float(data.get("descuento_valor") or 0), 0)
    except (TypeError, ValueError):
        descuento_valor = 0
    nota = str(data.get("nota") or "").strip()[:120]
    # texto final de display ("Mesa 3", "Para llevar", ...); laxa a propósito:
    # si NUM_MESAS baja, las cuentas viejas conservan su rótulo
    mesa = str(data.get("mesa") or "").strip()[:20]

    propina_tipo = data.get("propina_tipo", "porcentaje")
    if propina_tipo not in ("monto", "porcentaje"):
        propina_tipo = "porcentaje"
    try:
        propina_valor = max(float(data.get("propina_valor") or 0), 0)
    except (TypeError, ValueError):
        propina_valor = 0

    metodo_pago = data.get("metodo_pago", "Efectivo")
    if metodo_pago not in METODOS_PAGO:
        metodo_pago = "Efectivo"

    subtotal, total, _, propina = calcular_totales(
        items_in, descuento_tipo, descuento_valor, propina_tipo, propina_valor)

    db.execute("DELETE FROM items WHERE factura_id = ?", (fid,))
    for i in items_in:
        db.execute(
            "INSERT INTO items (factura_id, cantidad, descripcion, precio_unitario,"
            " subtotal, entregado) VALUES (?, ?, ?, ?, ?, ?)",
            (fid, i["cantidad"], i["descripcion"], i["precio_unitario"],
             int(round(i["cantidad"] * i["precio_unitario"])), i["entregado"]),
        )
    db.execute(
        "UPDATE facturas SET descuento_tipo=?, descuento_valor=?, subtotal=?, total=?, nota=?,"
        " propina_tipo=?, propina_valor=?, propina=?, metodo_pago=?, mesa=? WHERE id=?",
        (descuento_tipo, descuento_valor, subtotal, total, nota,
         propina_tipo, propina_valor, propina, metodo_pago, mesa, fid),
    )
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


def _cambiar_estado(fid, nuevo):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    if row["estado"] != "abierta":
        return jsonify({"error": "la factura ya no está abierta"}), 409
    # cobrar NO toca la etapa: en mostrador pagan primero y la cuenta sigue su
    # ciclo (enviar a cocina / entregar) ya pagada; anular tampoco la toca
    db.execute(
        "UPDATE facturas SET estado=?, fecha_cierre=?, reabierta=0 WHERE id=?",
        (nuevo, datetime.now().isoformat(timespec="seconds"), fid),
    )
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


@app.post("/api/facturas/<int:fid>/etapa")
def cambiar_etapa(fid):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    # la etapa avanza también sobre cuentas ya pagadas (pagan en el mostrador
    # y la comida se envía/entrega después); solo las anuladas quedan quietas
    if row["estado"] == "anulada":
        return jsonify({"error": "la factura está anulada"}), 409
    nueva = (request.get_json(force=True) or {}).get("etapa")
    if nueva not in ("enviada", "entregada"):
        return jsonify({"error": "etapa inválida"}), 400
    # solo se avanza; reimprimir comanda o repetir el toque no retrocede nada
    if ETAPAS.index(nueva) > ETAPAS.index(row["etapa"]):
        campo = "fecha_enviada" if nueva == "enviada" else "fecha_entregada"
        db.execute(
            f"UPDATE facturas SET etapa=?, {campo}=COALESCE({campo}, ?) WHERE id=?",
            (nueva, datetime.now().isoformat(timespec="seconds"), fid),
        )
        db.commit()
        row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


@app.post("/api/facturas/<int:fid>/mesa")
def cambiar_mesa(fid):
    """La mesa es un rótulo operativo: se puede mover también una pagada
    (mostrador: pagan primero y después se sientan). Solo anuladas no."""
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    if row["estado"] == "anulada":
        return jsonify({"error": "la factura está anulada"}), 409
    mesa = str((request.get_json(force=True) or {}).get("mesa") or "").strip()[:20]
    db.execute("UPDATE facturas SET mesa=? WHERE id=?", (mesa, fid))
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


@app.post("/api/facturas/<int:fid>/cerrar")
def cerrar_factura(fid):
    return _cambiar_estado(fid, "cerrada")


@app.post("/api/facturas/<int:fid>/anular")
def anular_factura(fid):
    return _cambiar_estado(fid, "anulada")


@app.post("/api/facturas/<int:fid>/archivar")
def archivar_factura(fid):
    """Cerrar cuenta: saca la pestaña de la caja ya, sin esperar la retención.
    Solo para cuentas pagadas; cerrar implica que también quedó entregada."""
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    if row["estado"] != "cerrada":
        return jsonify({"error": "solo se cierra una cuenta ya pagada"}), 409
    db.execute(
        "UPDATE facturas SET archivada=1,"
        " etapa=CASE WHEN etapa IN ('entregada','pagada') THEN etapa ELSE 'entregada' END,"
        " fecha_entregada=COALESCE(fecha_entregada, ?) WHERE id=?",
        (datetime.now().isoformat(timespec="seconds"), fid),
    )
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


@app.post("/api/facturas/<int:fid>/reabrir")
def reabrir_factura(fid):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return jsonify({"error": "factura no existe"}), 404
    if row["estado"] == "abierta":
        return jsonify(factura_dict(db, row))
    # la etapa se conserva; solo el legado etapa='pagada' se normaliza a
    # 'entregada' para que el re-cobro fluya normal; reabrir des-archiva
    db.execute(
        "UPDATE facturas SET estado='abierta', fecha_cierre=NULL, reabierta=1,"
        " archivada=0,"
        " etapa=CASE WHEN etapa='pagada' THEN 'entregada' ELSE etapa END"
        " WHERE id=?", (fid,))
    db.commit()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    return jsonify(factura_dict(db, row))


@app.get("/api/ventas")
def ventas_dia():
    db = get_db()
    fecha = request.args.get("fecha") or date.today().isoformat()
    rows = db.execute(
        "SELECT * FROM facturas WHERE estado='cerrada' AND date(fecha_apertura)=?"
        " ORDER BY numero_dia", (fecha,)
    ).fetchall()
    facturas = [factura_dict(db, r) for r in rows]
    por_metodo = {}
    for f in facturas:
        m = f.get("metodo_pago") or "Efectivo"
        acc = por_metodo.setdefault(m, {"total": 0, "propinas": 0, "num": 0})
        acc["total"] += f["total"]
        acc["propinas"] += f.get("propina", 0)
        acc["num"] += 1
    return jsonify({
        "fecha": fecha,
        "facturas": facturas,
        "total_dia": sum(f["total"] for f in facturas),
        "propinas_dia": sum(f.get("propina", 0) for f in facturas),
        "por_metodo": por_metodo,
        "num_facturas": len(facturas),
    })


@app.get("/api/export")
def export_csv():
    db = get_db()
    desde = request.args.get("desde") or date.today().isoformat()
    hasta = request.args.get("hasta") or desde
    rows = db.execute(
        "SELECT * FROM facturas WHERE estado='cerrada'"
        " AND date(fecha_apertura) BETWEEN ? AND ? ORDER BY fecha_apertura, numero_dia",
        (desde, hasta),
    ).fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Fecha", "Hora", "Factura", "Mesa", "Cantidad", "Item", "Precio Unitario",
                "Subtotal Item", "Subtotal Factura", "Descuento", "Total Factura",
                "Propina", "Total a Pagar", "Metodo Pago", "Nota",
                "Enviada a cocina", "Entregada"])

    def hora_o_vacio(iso):
        return datetime.fromisoformat(iso).strftime("%H:%M") if iso else ""

    total_rango = propinas_rango = 0
    for r in rows:
        f = factura_dict(db, r)
        dt = datetime.fromisoformat(f["fecha_apertura"])
        descuento = f["subtotal"] - f["total"]
        propina = f.get("propina", 0)
        total_rango += f["total"]
        propinas_rango += propina
        for idx, i in enumerate(f["items"]):
            w.writerow([
                dt.date().isoformat(), dt.strftime("%H:%M"), f["numero"],
                (f.get("mesa") or "") if idx == 0 else "",
                i["cantidad"], i["descripcion"], i["precio_unitario"], i["subtotal"],
                f["subtotal"] if idx == 0 else "", descuento if idx == 0 else "",
                f["total"] if idx == 0 else "", propina if idx == 0 else "",
                f["total_pagar"] if idx == 0 else "",
                (f.get("metodo_pago") or "Efectivo") if idx == 0 else "",
                f["nota"] if idx == 0 else "",
                hora_o_vacio(f.get("fecha_enviada")) if idx == 0 else "",
                hora_o_vacio(f.get("fecha_entregada")) if idx == 0 else "",
            ])
    w.writerow([])
    w.writerow(["TOTAL", desde if desde == hasta else f"{desde} a {hasta}",
                f"{len(rows)} facturas", "", "", "", "", "", "", "", total_rango,
                propinas_rango, total_rango + propinas_rango, "", "", "", ""])

    out = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    nombre = f"ventas_pizzicleta_{desde}" + ("" if desde == hasta else f"_{hasta}") + ".csv"
    return send_file(out, mimetype="text/csv", as_attachment=True, download_name=nombre)


@app.get("/api/backup")
def backup_db():
    """Descarga una copia consistente de la base (sirve para respaldo o para
    mover el POS a otro equipo)."""
    import tempfile
    db = get_db()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as t:
        ruta = Path(t.name)
    destino = sqlite3.connect(ruta)
    db.backup(destino)
    destino.close()
    datos = ruta.read_bytes()
    ruta.unlink(missing_ok=True)
    nombre = f"pos-{date.today().isoformat()}.db"
    return send_file(io.BytesIO(datos), mimetype="application/octet-stream",
                     as_attachment=True, download_name=nombre)


# ---------- retiros y pagos (salidas de efectivo) ----------

@app.get("/api/movimientos")
def listar_movimientos():
    db = get_db()
    fecha = request.args.get("fecha") or date.today().isoformat()
    rows = db.execute(
        "SELECT * FROM movimientos WHERE fecha = ? ORDER BY id", (fecha,)
    ).fetchall()
    movs = [dict(r) for r in rows]
    return jsonify({"fecha": fecha, "movimientos": movs,
                    "total": sum(m["monto"] for m in movs)})


@app.post("/api/movimientos")
def crear_movimiento():
    db = get_db()
    data = request.get_json(force=True)
    tipo = data.get("tipo", "Retiro")
    if tipo not in TIPOS_MOVIMIENTO:
        tipo = "Retiro"
    origen = data.get("origen", "Efectivo")
    if origen not in ORIGENES_MOVIMIENTO:
        origen = "Efectivo"
    concepto = str(data.get("concepto") or "").strip()[:120]
    try:
        monto = max(int(data.get("monto") or 0), 0)
    except (TypeError, ValueError):
        monto = 0
    if monto <= 0:
        return jsonify({"error": "el monto debe ser mayor a 0"}), 400
    ahora = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        "INSERT INTO movimientos (fecha, tipo, concepto, monto, creado_en, origen)"
        " VALUES (?,?,?,?,?,?)",
        (date.today().isoformat(), tipo, concepto, monto, ahora, origen),
    )
    db.commit()
    row = db.execute("SELECT * FROM movimientos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.delete("/api/movimientos/<int:mid>")
def eliminar_movimiento(mid):
    db = get_db()
    row = db.execute("SELECT * FROM movimientos WHERE id = ?", (mid,)).fetchone()
    if row is None:
        return jsonify({"error": "movimiento no existe"}), 404
    db.execute("DELETE FROM movimientos WHERE id = ?", (mid,))
    db.commit()
    return jsonify({"ok": True})


# ---------- apertura y cierre de caja ----------

def _cierre_dict(row):
    if row is None:
        return None
    c = dict(row)
    for campo in ("conteo_efectivo", "conteo_base_siguiente"):
        try:
            c[campo] = json.loads(c.get(campo) or "{}")
        except ValueError:
            c[campo] = {}
    return c


def _limpiar_conteo(conteo):
    """{denominación: cantidad} con solo enteros positivos."""
    if not isinstance(conteo, dict):
        return {}
    return {str(k): int(v) for k, v in conteo.items()
            if str(k).isdigit() and isinstance(v, (int, float)) and v > 0}


@app.get("/api/apertura")
def get_apertura():
    db = get_db()
    fecha = request.args.get("fecha") or date.today().isoformat()
    row = db.execute("SELECT * FROM aperturas WHERE fecha = ?", (fecha,)).fetchone()
    # la base sugerida es la que el cierre anterior declaró dejar en caja
    anterior = db.execute(
        "SELECT COALESCE(base_siguiente, base) AS b FROM cierres"
        " WHERE fecha < ? ORDER BY fecha DESC LIMIT 1",
        (fecha,),
    ).fetchone()
    return jsonify({"fecha": fecha, "apertura": _cierre_dict(row),
                    "base_sugerida": anterior["b"] if anterior else 0})


@app.post("/api/apertura")
def guardar_apertura():
    db = get_db()
    data = request.get_json(force=True)
    fecha = data.get("fecha") or date.today().isoformat()
    try:
        base = max(int(data.get("base") or 0), 0)
    except (TypeError, ValueError):
        base = 0
    conteo = _limpiar_conteo(data.get("conteo_efectivo"))
    db.execute(
        "INSERT INTO aperturas (fecha, base, conteo_efectivo, guardado_en)"
        " VALUES (?,?,?,?)"
        " ON CONFLICT(fecha) DO UPDATE SET base=excluded.base,"
        " conteo_efectivo=excluded.conteo_efectivo, guardado_en=excluded.guardado_en",
        (fecha, base, json.dumps(conteo),
         datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    row = db.execute("SELECT * FROM aperturas WHERE fecha = ?", (fecha,)).fetchone()
    return jsonify({"fecha": fecha, "apertura": _cierre_dict(row)})


def _esperados_dia(db, fecha):
    """Dinero recibido por método (venta + propina) de las cerradas del día."""
    rows = db.execute(
        "SELECT metodo_pago, SUM(total + propina) AS t FROM facturas"
        " WHERE estado='cerrada' AND date(fecha_apertura)=? GROUP BY metodo_pago",
        (fecha,),
    ).fetchall()
    por = {r["metodo_pago"] or "Efectivo": r["t"] or 0 for r in rows}
    sal_rows = db.execute(
        "SELECT origen, COALESCE(SUM(monto), 0) AS t FROM movimientos"
        " WHERE fecha = ? GROUP BY origen", (fecha,),
    ).fetchall()
    sal = {r["origen"] or "Efectivo": r["t"] or 0 for r in sal_rows}
    sal_efectivo = sal.get("Efectivo", 0)
    sal_transf = sal.get("Transferencia", 0)
    return {
        "efectivo": por.get("Efectivo", 0),
        "datafono": por.get("Datáfono", 0),
        "transferencias": por.get("Nequi", 0) + por.get("Transferencia", 0),
        "salidas": sal_efectivo + sal_transf,
        "salidas_efectivo": sal_efectivo,
        "salidas_transferencias": sal_transf,
    }


@app.get("/api/cierre")
def get_cierre():
    db = get_db()
    fecha = request.args.get("fecha") or date.today().isoformat()
    esperados = _esperados_dia(db, fecha)
    row = db.execute("SELECT * FROM cierres WHERE fecha = ?", (fecha,)).fetchone()
    # base sugerida: la apertura registrada ese día; si no hay, la base del
    # último cierre anterior (base fija que quedó para el día siguiente)
    apertura = db.execute(
        "SELECT base FROM aperturas WHERE fecha = ?", (fecha,)).fetchone()
    anterior = db.execute(
        "SELECT COALESCE(base_siguiente, base) AS b FROM cierres"
        " WHERE fecha < ? ORDER BY fecha DESC LIMIT 1",
        (fecha,),
    ).fetchone()
    base_sugerida = (apertura["base"] if apertura
                     else anterior["b"] if anterior else 0)
    return jsonify({"fecha": fecha, "esperados": esperados,
                    "cierre": _cierre_dict(row),
                    "base_sugerida": base_sugerida})


@app.post("/api/cierre")
def guardar_cierre():
    db = get_db()
    data = request.get_json(force=True)
    fecha = data.get("fecha") or date.today().isoformat()

    def entero(campo):
        try:
            return max(int(data.get(campo) or 0), 0)
        except (TypeError, ValueError):
            return 0

    base = entero("base")
    efectivo = entero("efectivo_contado")
    datafono = entero("datafono_contado")
    transf = entero("transferencias_contado")

    # base que se deja en la caja para abrir el día siguiente (NULL = no declarada)
    bs = data.get("base_siguiente")
    try:
        base_siguiente = max(int(bs), 0) if bs not in (None, "") else None
    except (TypeError, ValueError):
        base_siguiente = None

    conteo = _limpiar_conteo(data.get("conteo_efectivo"))
    conteo_bs = _limpiar_conteo(data.get("conteo_base_siguiente"))

    esp = _esperados_dia(db, fecha)
    total_final = (efectivo - base) + datafono + transf
    # las salidas (retiros/pagos) reducen lo que debe quedar del día
    esperado_total = (esp["efectivo"] + esp["datafono"] + esp["transferencias"]
                      - esp["salidas"])
    diferencia = total_final - esperado_total

    db.execute(
        "INSERT INTO cierres (fecha, base, efectivo_contado, datafono_contado,"
        " transferencias_contado, esperado_efectivo, esperado_datafono,"
        " esperado_transferencias, total_final, diferencia, guardado_en, conteo_efectivo,"
        " salidas, base_siguiente, conteo_base_siguiente)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(fecha) DO UPDATE SET base=excluded.base,"
        " efectivo_contado=excluded.efectivo_contado,"
        " datafono_contado=excluded.datafono_contado,"
        " transferencias_contado=excluded.transferencias_contado,"
        " esperado_efectivo=excluded.esperado_efectivo,"
        " esperado_datafono=excluded.esperado_datafono,"
        " esperado_transferencias=excluded.esperado_transferencias,"
        " total_final=excluded.total_final, diferencia=excluded.diferencia,"
        " guardado_en=excluded.guardado_en, conteo_efectivo=excluded.conteo_efectivo,"
        " salidas=excluded.salidas, base_siguiente=excluded.base_siguiente,"
        " conteo_base_siguiente=excluded.conteo_base_siguiente",
        (fecha, base, efectivo, datafono, transf,
         esp["efectivo"], esp["datafono"], esp["transferencias"],
         total_final, diferencia,
         datetime.now().isoformat(timespec="seconds"), json.dumps(conteo),
         esp["salidas"], base_siguiente, json.dumps(conteo_bs)),
    )
    db.commit()
    row = db.execute("SELECT * FROM cierres WHERE fecha = ?", (fecha,)).fetchone()
    return jsonify({"fecha": fecha, "esperados": esp, "cierre": _cierre_dict(row)})


# ---------- cuadres de turno (auditoría intermedia de caja) ----------

@app.get("/api/cuadres")
def listar_cuadres():
    db = get_db()
    fecha = request.args.get("fecha") or date.today().isoformat()
    rows = db.execute(
        "SELECT * FROM cuadres WHERE fecha = ? ORDER BY id", (fecha,)
    ).fetchall()
    out = []
    for r in rows:
        c = dict(r)
        try:
            c["conteo_efectivo"] = json.loads(c.get("conteo_efectivo") or "{}")
        except ValueError:
            c["conteo_efectivo"] = {}
        out.append(c)
    return jsonify({"fecha": fecha, "cuadres": out})


@app.post("/api/cuadres")
def crear_cuadre():
    """Cuadre intermedio del turno: fotografía contado vs esperado en ese
    momento (base + ventas efectivo − salidas, y transferencias del día)."""
    db = get_db()
    data = request.get_json(force=True)
    fecha = date.today().isoformat()

    def entero(campo):
        try:
            return max(int(data.get(campo) or 0), 0)
        except (TypeError, ValueError):
            return 0

    efectivo = entero("efectivo_contado")
    transf = entero("transferencias_contado")
    conteo = _limpiar_conteo(data.get("conteo_efectivo"))

    esp = _esperados_dia(db, fecha)
    ap = db.execute("SELECT base FROM aperturas WHERE fecha = ?", (fecha,)).fetchone()
    base = ap["base"] if ap else 0
    esperado_ef = base + esp["efectivo"] - esp["salidas_efectivo"]
    esperado_tr = esp["transferencias"] - esp["salidas_transferencias"]

    cur = db.execute(
        "INSERT INTO cuadres (fecha, creado_en, base, efectivo_contado,"
        " transferencias_contado, esperado_efectivo, esperado_transferencias,"
        " dif_efectivo, dif_transferencias, conteo_efectivo)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (fecha, datetime.now().isoformat(timespec="seconds"), base, efectivo,
         transf, esperado_ef, esperado_tr,
         efectivo - esperado_ef, transf - esperado_tr, json.dumps(conteo)),
    )
    db.commit()
    row = db.execute("SELECT * FROM cuadres WHERE id = ?", (cur.lastrowid,)).fetchone()
    c = dict(row)
    c["conteo_efectivo"] = conteo
    return jsonify(c), 201


# ---------- ticket 80mm ----------

def _fmt(n):
    return f"${n:,.0f}".replace(",", ".")


@app.get("/ticket/<int:fid>")
def ticket(fid):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return "Factura no encontrada", 404
    f = factura_dict(db, row)
    dt = datetime.fromisoformat(f["fecha_cierre"] or f["fecha_apertura"])
    descuento = f["subtotal"] - f["total"]
    auto_print = request.args.get("print") == "1"

    lineas = "".join(
        f'<tr><td class="c">{i["cantidad"]:g}</td>'
        f'<td class="d">{html.escape(i["descripcion"])}</td>'
        f'<td class="v">{_fmt(i["subtotal"])}</td></tr>'
        for i in f["items"]
    )
    bloque_desc = ""
    if descuento > 0:
        etiqueta = ("Descuento"
                    if f["descuento_tipo"] == "monto"
                    else f"Descuento ({f['descuento_valor']:g}%)")
        bloque_desc = (
            f'<div class="tot-row"><span>Subtotal</span><span>{_fmt(f["subtotal"])}</span></div>'
            f'<div class="tot-row"><span>{etiqueta}</span><span>-{_fmt(descuento)}</span></div>'
        )
    propina = f.get("propina", 0)
    bloque_propina = ""
    if propina > 0:
        etiqueta_p = ("Propina"
                      if f["propina_tipo"] == "monto"
                      else f"Propina ({f['propina_valor']:g}%)")
        bloque_propina = (
            f'<div class="tot-row"><span>{etiqueta_p}</span><span>{_fmt(propina)}</span></div>'
            f'<div class="total"><span>A PAGAR</span><span>{_fmt(f["total_pagar"])}</span></div>'
        )
    nota = f'<p class="nota">{html.escape(f["nota"])}</p>' if f["nota"] else ""
    borrador = "" if f["estado"] == "cerrada" else '<p class="borrador">— BORRADOR —</p>'
    script = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),150))</script>" if auto_print else ""

    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ticket {f["numero"]}</title>
<style>
@font-face {{ font-family:'IBM Plex Mono'; src:url('/static/fonts/ibmplexmono-400.woff2') format('woff2'); font-weight:400; }}
@font-face {{ font-family:'IBM Plex Mono'; src:url('/static/fonts/ibmplexmono-600.woff2') format('woff2'); font-weight:600; }}
@page {{ size: 80mm auto; margin: 0; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:#fff; }}
body {{
  width:72mm; margin:0 auto; padding:4mm 0 8mm;
  font-family:'IBM Plex Mono', 'Courier New', monospace;
  font-size:12px; line-height:1.45; color:#000;
  -webkit-print-color-adjust:exact; print-color-adjust:exact;
}}
img.logo {{ display:block; width:28mm; margin:0 auto 2mm; }}
h1 {{ font-size:15px; font-weight:600; text-align:center; letter-spacing:.08em; }}
.sub {{ text-align:center; font-size:10px; letter-spacing:.14em; text-transform:uppercase; margin-bottom:2mm; }}
.meta {{ text-align:center; font-size:11px; margin-bottom:2mm; }}
.sep {{ border:none; border-top:1px dashed #000; margin:2mm 0; }}
table {{ width:100%; border-collapse:collapse; }}
td {{ vertical-align:top; padding:1px 0; }}
td.c {{ width:9mm; }}
td.d {{ padding-right:2mm; word-break:break-word; }}
td.v {{ text-align:right; white-space:nowrap; }}
.tot-row {{ display:flex; justify-content:space-between; font-size:12px; }}
.total {{ display:flex; justify-content:space-between; font-size:17px; font-weight:600; margin-top:1mm; }}
.nota {{ text-align:center; font-size:11px; margin-top:2mm; }}
.borrador {{ text-align:center; font-weight:600; letter-spacing:.2em; margin-bottom:2mm; }}
.pie {{ text-align:center; font-size:10px; margin-top:3mm; }}
@media screen {{
  body {{ box-shadow:0 2px 24px rgba(0,0,0,.18); margin:24px auto; padding:6mm 4mm 10mm; }}
  html {{ background:#e8e4dd; }}
}}
</style></head><body>
<img class="logo" src="/static/logo-ticket.png" alt="La Pizzicleta">
<h1>LA PIZZICLETA</h1>
<p class="sub">Pizzicleta Social Club</p>
{borrador}
<p class="meta">{dt.strftime("%d/%m/%Y %H:%M")}<br>Cuenta {f["numero"]}{f'<br>{html.escape(f["mesa"])}' if f.get("mesa") else ""}<br>Pago: {html.escape(f.get("metodo_pago") or "Efectivo")}</p>
{nota}
<hr class="sep">
<table>{lineas}</table>
<hr class="sep">
{bloque_desc}
<div class="total"><span>TOTAL</span><span>{_fmt(f["total"])}</span></div>
{bloque_propina}
<hr class="sep">
<p class="pie">Una pizza para sanar el alma<br>@lapizzicleta &middot; Cali, CO</p>
{script}
</body></html>"""


# ---------- comanda 80mm (sin precios; no modifica la BD) ----------
# Se imprimen DOS tickets en un solo trabajo: COCINA y BEBIDAS (la impresora
# corta entre páginas). La clasificación sale de la categoría en menu.json;
# lo que no esté en el menú (ítems manuales) va a cocina.

CATS_BEBIDAS = {"bebidas", "cervezas", "licor", "adicion de licor",
                "gaseosas en combo", "notas de sabores"}
# para ítems manuales que no están en el menú; los del menú se clasifican
# por su categoría (un combo con gaseosa sigue siendo de cocina)
PALABRAS_BEBIDA = ("cerveza", "gaseosa", "limonada", "jugo", "soda", "agua",
                   "michelada", "vino", "licor", "coctel", "cafe", "refajo",
                   "malteada", "cocacola", "coca cola", "sprite", "quatro",
                   "ginger", "tonica", "club colombia", "corona", "aguila",
                   "poker", "heineken", "stella", "budweiser")


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower().strip())
    return "".join(c for c in s if not unicodedata.combining(c))


def _mapa_categorias():
    if not MENU_JSON.exists():
        return {}
    try:
        menu = json.loads(MENU_JSON.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {_norm(i.get("nombre")): _norm(i.get("categoria")) for i in menu}


@app.get("/comanda/<int:fid>")
def comanda(fid):
    db = get_db()
    row = db.execute("SELECT * FROM facturas WHERE id = ?", (fid,)).fetchone()
    if row is None:
        return "Factura no encontrada", 404
    f = factura_dict(db, row)
    ahora = datetime.now()
    auto_print = request.args.get("print") == "1"

    items = [i for i in f["items"] if (i["descripcion"] or "").strip()]
    mapa = _mapa_categorias()

    def es_bebida(desc):
        n = _norm(desc)
        # los sabores/acompañantes elegidos van en un sufijo "(...)" que no
        # está en el menú; se quita para clasificar por la categoría real
        sin_sufijo = _norm(re.sub(r"\s*\([^()]*\)$", "", desc or ""))
        cat = mapa.get(n) or mapa.get(sin_sufijo)
        if cat is not None:
            return cat in CATS_BEBIDAS
        return any(p in n for p in PALABRAS_BEBIDA)

    cocina, bebidas = [], []
    for i in items:
        (bebidas if es_bebida(i["descripcion"]) else cocina).append(i)
    secciones = [("COCINA", cocina), ("BEBIDAS", bebidas)]
    secciones = [s for s in secciones if s[1]] or [("COCINA", items)]

    mesa = f'<p class="mesa">{html.escape(f["mesa"])}</p>' if f.get("mesa") else ""
    nota = f'<p class="nota">{html.escape(f["nota"])}</p>' if f["nota"] else ""
    # el frontend marca 'enviada' antes de abrir la comanda, así que fecha_enviada
    # no distingue la primera impresión: la reimpresión la declara la caja con ?re=1
    reimpresion = '<p class="reimp">— REIMPRESIÓN —</p>' if request.args.get("re") == "1" else ""
    script = "<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),150))</script>" if auto_print else ""

    def seccion_html(titulo, its):
        lineas = "".join(
            f'<tr><td class="c">{i["cantidad"]:g}×</td>'
            f'<td class="d">{html.escape(i["descripcion"])}</td></tr>'
            for i in its
        )
        return f"""<section class="pagina">
<h1>COMANDA · {titulo}</h1>
{reimpresion}
<p class="meta">Cuenta {f["numero"]} &middot; {ahora.strftime("%d/%m/%Y %H:%M")}</p>
{mesa}
<hr class="sep">
<table>{lineas}</table>
{nota}
</section>"""

    cuerpo = "".join(seccion_html(t, its) for t, its in secciones)

    return f"""<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comanda {f["numero"]}</title>
<style>
@font-face {{ font-family:'IBM Plex Mono'; src:url('/static/fonts/ibmplexmono-400.woff2') format('woff2'); font-weight:400; }}
@font-face {{ font-family:'IBM Plex Mono'; src:url('/static/fonts/ibmplexmono-600.woff2') format('woff2'); font-weight:600; }}
@page {{ size: 80mm auto; margin: 0; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ background:#fff; }}
body {{
  width:72mm; margin:0 auto; padding:4mm 0 8mm;
  font-family:'IBM Plex Mono', 'Courier New', monospace;
  font-size:14px; line-height:1.5; color:#000;
  -webkit-print-color-adjust:exact; print-color-adjust:exact;
}}
h1 {{ font-size:15px; font-weight:600; text-align:center; letter-spacing:.14em; }}
.meta {{ text-align:center; font-size:12px; margin-bottom:1mm; }}
.mesa {{ text-align:center; font-size:19px; font-weight:600; margin:1mm 0; }}
.reimp {{ text-align:center; font-weight:600; letter-spacing:.2em; margin:1mm 0; }}
.sep {{ border:none; border-top:1px dashed #000; margin:2mm 0; }}
table {{ width:100%; border-collapse:collapse; }}
td {{ vertical-align:top; padding:2px 0; }}
td.c {{ width:12mm; font-weight:600; font-size:16px; }}
td.d {{ font-size:15px; word-break:break-word; }}
.nota {{ text-align:center; font-size:13px; font-weight:600; margin-top:2mm; }}
.pagina {{ page-break-after:always; }}
.pagina:last-child {{ page-break-after:auto; }}
@media screen {{
  body {{ box-shadow:0 2px 24px rgba(0,0,0,.18); margin:24px auto; padding:6mm 4mm 10mm; }}
  html {{ background:#e8e4dd; }}
  .pagina + .pagina {{ border-top:2px dashed #999; margin-top:8mm; padding-top:6mm; }}
}}
</style></head><body>
{cuerpo}
{script}
</body></html>"""


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("POS_PORT", 8085)))
