# Setup — correr el POS en el computador de la pizzería

Guía para instalar y dejar corriendo el POS directamente en el PC de caja de la
sede (Windows), sin depender del Mac. Una sola vez, ~15 minutos.

> **Regla de oro:** el servidor debe correr en **UN solo equipo a la vez**.
> Si se pasa al PC de la pizzería, en el Mac ya no se arranca (o quedarían dos
> bases de datos distintas). La base con todas las ventas es `data/pos.db`.

## 1. Instalar Python (una sola vez)

1. Descargar Python desde <https://www.python.org/downloads/> (botón amarillo).
2. Al ejecutar el instalador, **marcar la casilla "Add python.exe to PATH"**
   (abajo del todo) antes de darle *Install Now*.
3. Listo. No hace falta nada más: el lanzador instala Flask solo la primera vez.

## 2. Instalar Git y clonar el POS (una sola vez)

El código vive en GitHub: <https://github.com/angelosalazarb/POSLaPizzicleta>

1. Instalar **Git para Windows**: <https://git-scm.com/download/win> (siguiente,
   siguiente, siguiente — los valores por defecto sirven).
2. Abrir `cmd` y clonar:

   ```
   git clone https://github.com/angelosalazarb/POSLaPizzicleta.git C:\Pizzicleta\pos
   ```

Queda así:

```
C:\Pizzicleta\pos\
├── app.py
├── pos.html
├── run-windows.bat          ← el lanzador
├── actualizar-windows.bat   ← trae mejoras desde GitHub (git pull)
├── static\                  (logo, fuentes)
└── data\
    ├── menu.json            (catálogo de la carta para el autocompletado)
    └── pos.db               ← LA BASE DE VENTAS (no viene en GitHub, ver paso 2b)
```

**Actualizaciones futuras:** doble clic a `actualizar-windows.bat` (cierra antes
la ventana del servidor y vuelve a abrir `run-windows.bat`). La base de datos
nunca se toca con las actualizaciones: está excluida del repositorio a propósito.

## 2b. Mover la base con lo ya vendido (desde el Mac)

Las ventas ya registradas viven en `data/pos.db` del equipo donde corría el
servidor (el Mac). Para traerlas, **con el servidor del Mac todavía corriendo**:

1. En el navegador del PC de la pizzería abrir:
   `http://<IP-del-Mac>:8085/api/backup`
   — descarga una copia consistente con nombre `pos-AAAA-MM-DD.db` (funciona
   aunque el servidor esté en uso).
2. **Apagar el servidor del Mac** (Ctrl+C en su terminal) — desde aquí manda el PC.
3. Renombrar el archivo descargado a `pos.db` y ponerlo en
   `C:\Pizzicleta\pos\data\pos.db`.
4. Arrancar `run-windows.bat` y verificar en "Ventas de hoy" que aparecen las
   ventas del día.

Si no hay ventas previas que conservar, saltarse esto: el sistema crea una base
vacía al arrancar. El mismo enlace `/api/backup` sirve después para el respaldo
diario (paso 7).

## 3. Arrancar

Doble clic en **`run-windows.bat`**. La primera vez instala Flask (necesita
internet un momento); después arranca en segundos. La ventana negra que queda
abierta ES el servidor — minimizarla, no cerrarla (cerrarla apaga el POS).

- En ese mismo PC: abrir Chrome en <http://localhost:8085>
- Guardarlo como marcador o crear un acceso directo de Chrome a esa dirección.

## 4. Firewall (solo si otro equipo va a entrar)

Si el POS se usa solo en ese PC, saltarse este paso. Para entrar desde otro
equipo o un celular de la red del local:

1. La primera vez que arranca, Windows pregunta si permitir el acceso de Python
   a la red → **Permitir acceso** (redes privadas).
2. Averiguar la IP del PC: abrir `cmd` → `ipconfig` → "Dirección IPv4"
   (ej. `192.168.0.2`).
3. Desde el otro equipo: `http://192.168.0.2:8085`.
4. Recomendado: reservar esa IP en el router (reservación DHCP) para que no cambie.

## 5. Arranque automático al prender el PC (opcional, recomendado)

1. Clic derecho sobre `run-windows.bat` → **Crear acceso directo**.
2. Presionar `Windows + R`, escribir `shell:startup` y Enter — se abre la
   carpeta de inicio.
3. Mover el acceso directo ahí.

Con eso, cada vez que prendan el PC el POS arranca solo.

## 6. Impresora SAT POS80

Igual que siempre (detalle completo en el README):

- Driver SAT instalado y papel **POS80** en el driver.
- Al imprimir desde Chrome: destino SAT, papel POS80, **márgenes: ninguno**,
  escala 100%, sin encabezados. Chrome lo recuerda.
- Impresión sin diálogo: acceso directo de Chrome con `--kiosk-printing`
  y la SAT como impresora predeterminada de Windows.

## 7. Respaldo diario (importante)

Toda la información vive en un solo archivo: `data\pos.db`.

- La vía fácil: abrir `http://localhost:8085/api/backup` al final del día —
  descarga la copia ya nombrada con la fecha (`pos-2026-08-30.db`). Guardarla
  en `C:\Pizzicleta\respaldos\`, un USB o la nube.
- También sirve copiar y pegar el archivo `data\pos.db` directamente (se puede
  con el servidor corriendo).
- El **Exportar CSV** de "Ventas de hoy" sirve para contabilidad, pero **no**
  reemplaza el respaldo del `.db`.

## 8. Actualizar precios / productos del menú

El autocompletado sale de `data\menu.json`. Es un archivo de texto editable
(Bloc de notas): cada producto tiene `nombre`, `precio` y `categoria`. Editar,
guardar y refrescar el navegador (Ctrl+F5). No hace falta reiniciar el servidor.

## 9. Problemas comunes

| Síntoma | Solución |
|---|---|
| "No se encontró Python" al abrir el .bat | Reinstalar Python marcando "Add python.exe to PATH" |
| La página no abre en localhost:8085 | ¿Está abierta la ventana negra del servidor? Volver a dar doble clic al .bat |
| Otro equipo no puede entrar | Firewall (paso 4) o cambió la IP del PC (reservarla en el router) |
| El ticket sale cortado o gigante | Revisar papel POS80 y márgenes "ninguno" en el diálogo de Chrome |
| "Address already in use" al arrancar | Ya hay un servidor corriendo (otra ventana negra abierta) — usar esa |
