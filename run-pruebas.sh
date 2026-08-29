#!/bin/sh
# Instancia de PRUEBAS del POS en el Mac (puerto 8086, base propia).
# No toca producción: el servidor real corre en el PC de la pizzería (8085)
# con data/pos.db — regla de un solo servidor.
#
# Uso:    ./run-pruebas.sh            (crea data/pos-pruebas.db desde pos.db la 1ª vez)
#         ./run-pruebas.sh --reset    (vuelve a copiar la base real y empieza limpio)
cd "$(dirname "$0")" || exit 1

DB="data/pos-pruebas.db"

if [ "$1" = "--reset" ]; then
  rm -f "$DB"
fi

if [ ! -f "$DB" ]; then
  if [ -f "data/pos.db" ]; then
    cp "data/pos.db" "$DB"
    echo ">> Base de pruebas creada como copia de data/pos.db"
  else
    echo ">> No hay data/pos.db local; la base de pruebas arranca vacía"
  fi
fi

echo ">> POS de PRUEBAS en http://localhost:8086  (Ctrl+C para detener)"
POS_DB="$DB" POS_PORT=8086 exec uv run --with flask app.py
