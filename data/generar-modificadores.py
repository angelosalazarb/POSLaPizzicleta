#!/usr/bin/env python3
"""Genera data/modificadores.json y anota data/menu.json con los grupos
de modificadores de cada producto, a partir de la carta scrapeada de niceeat
(data/carta-niceeat-completa.json).

Correr después de re-scrapear la carta:  python3 data/generar-modificadores.py
"""

import json
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent
CARTA = BASE / "carta-niceeat-completa.json"
MENU = BASE / "menu.json"
MODS = BASE / "modificadores.json"

# reglas por grupo (niceeat no exporta min/max; salen de la carta pública).
# Los grupos que no estén acá son opcionales, hasta 4 unidades.
REGLAS = {
    "Elige 2 sabores": {"min": 2, "max": 2},
    "Elige un sabor": {"min": 1, "max": 1},
    "GASEOSAS EN COMBO": {"min": 1, "max": 1},
}
REGLA_DEFECTO = {"min": 0, "max": 4}


def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def main():
    carta = json.loads(CARTA.read_text(encoding="utf-8"))
    menu = json.loads(MENU.read_text(encoding="utf-8"))

    # grupos que alguna variación realmente usa
    usados = {g for p in carta["productos"] for v in p["variaciones"]
              for g in v["grupos_modificadores"]}

    # opciones por grupo, deduplicadas por nombre normalizado
    grupos = {}
    for m in carta["modificadores"]:
        g = m["grupo"]
        if g not in usados or m.get("disponible") != "Si":
            continue
        ops = grupos.setdefault(g, {})
        clave = norm(m["nombre"])
        if clave not in ops:
            ops[clave] = {"nombre": m["nombre"].strip(),
                          "precio": int(m.get("precio") or 0)}

    salida = {}
    for g in sorted(grupos, key=norm):
        regla = REGLAS.get(g, REGLA_DEFECTO)
        salida[g] = {
            "obligatorio": regla["min"] > 0,
            "min": regla["min"],
            "max": regla["max"],
            "opciones": sorted(grupos[g].values(), key=lambda o: norm(o["nombre"])),
        }
    MODS.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    # anotar el menú: "Producto — Variación" (o solo el producto) -> grupos
    variantes = {}
    for p in carta["productos"]:
        for v in p["variaciones"]:
            gs = [g for g in v["grupos_modificadores"] if g in salida]
            variantes[norm(p["nombre"] + " — " + v["nombre"])] = gs
            variantes.setdefault(norm(p["nombre"]), gs)

    anotados = 0
    for item in menu:
        gs = variantes.get(norm(item["nombre"])) or []
        if gs:
            item["modificadores"] = gs
            anotados += 1
        else:
            item.pop("modificadores", None)
    MENU.write_text(json.dumps(menu, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    print(f"modificadores.json: {len(salida)} grupos "
          f"({sum(len(v['opciones']) for v in salida.values())} opciones)")
    print(f"menu.json: {anotados} de {len(menu)} productos con modificadores")


if __name__ == "__main__":
    main()
