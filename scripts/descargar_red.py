"""Descarga la red vial de Lima desde OpenStreetMap y la guarda en un formato compacto.

Se corre UNA sola vez, en la PC (no en Render). El resultado (data/red_lima.json) se sube al repo.

    pip install -r requirements-dev.txt
    python scripts/descargar_red.py

Qué hace:
  1. Lee la zona de data/zona.json y descarga la red de calles para autos con OSMnx.
  2. Agrega velocidades y tiempos de viaje a cada calle.
  3. Se queda con la componente fuertemente conexa más grande (de cualquier esquina se llega a cualquier otra).
  4. Guarda data/red_lima.json: "nodos" = [[lat, lng], ...] (el índice es el id) y
     "aristas" = [[i, j, minutos], ...] dirigidas (respetan los sentidos); entre aristas paralelas, la de menor tiempo.
  5. Asigna a cada establecimiento de data/grafo.json su nodo más cercano ("nodo") y la distancia a él.
  6. Guarda hospitales y clínicas de OSM de la zona en data/establecimientos_osm_candidatos.json
     (con "revisar": true). NO se agregan a grafo.json: el equipo los valida contra RENIPRESS (T6).

Si solo cambiaste establecimientos en grafo.json (T6), no hace falta descargar de nuevo:

    python scripts/descargar_red.py --solo-asignar

Datos: © colaboradores de OpenStreetMap, licencia ODbL.
"""
import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import osmnx as ox  # noqa: E402  (solo se necesita en la PC de desarrollo)
import pandas as pd  # noqa: E402

from app.motor import red_vial  # noqa: E402  (haversine y nodo más cercano propios)

DATA = RAIZ / "data"
ARCHIVO_RED = DATA / "red_lima.json"
ARCHIVO_CANDIDATOS = DATA / "establecimientos_osm_candidatos.json"
ATRIBUCION = "© colaboradores de OpenStreetMap, licencia ODbL"


def miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def con_reintentos(funcion, intentos: int, espera_s: int):
    """Overpass a veces responde 'servidor saturado': se reintenta con pausa creciente."""
    for intento in range(1, intentos + 1):
        try:
            return funcion()
        except Exception as e:  # noqa: BLE001  (osmnx lanza varios tipos: red, tiempo, respuesta vacía)
            if intento == intentos:
                raise
            pausa = espera_s * intento
            print(f"  intento {intento}/{intentos} falló ({type(e).__name__}: {str(e)[:120]}); reintento en {pausa} s")
            time.sleep(pausa)


def descargar_grafo(centro: tuple[float, float], radio_m: int):
    """Pasos 1–3. Nombres de OSMnx 2.x: ox.routing.add_edge_* y ox.truncate.largest_component."""
    print(f"Descargando la red de calles (radio {radio_m} m)…")
    # dist_type="bbox" (valor por defecto): la zona descargada es el cuadrado que circunscribe al círculo.
    G = ox.graph_from_point(centro, dist=radio_m, network_type="drive")
    print(f"  descargada: {miles(G.number_of_nodes())} nodos, {miles(G.number_of_edges())} aristas")
    G = ox.routing.add_edge_speeds(G)          # km/h por calle (de OSM o imputada por tipo de vía)
    G = ox.routing.add_edge_travel_times(G)    # segundos por calle = longitud / velocidad
    G = ox.truncate.largest_component(G, strongly=True)
    print(f"  componente fuertemente conexa más grande: {miles(G.number_of_nodes())} nodos")
    return G


def compactar(G) -> tuple[list, list]:
    """Formato compacto: nodos [lat, lng] y aristas [i, j, minutos]; entre paralelas, la de menor tiempo."""
    ids = sorted(G.nodes)
    indice = {n: i for i, n in enumerate(ids)}
    nodos = [[round(G.nodes[n]["y"], 6), round(G.nodes[n]["x"], 6)] for n in ids]
    mejores: dict[tuple[int, int], float] = {}
    for u, v, datos in G.edges(data=True):
        if u == v:
            continue   # un lazo nunca está en un camino mínimo
        minutos = datos["travel_time"] / 60
        clave = (indice[u], indice[v])
        if clave not in mejores or minutos < mejores[clave]:
            mejores[clave] = minutos
    aristas = [[i, j, round(m, 3)] for (i, j), m in sorted(mejores.items())]
    return nodos, aristas


def guardar_red(nodos: list, aristas: list, zona: dict) -> float:
    meta = {
        "fuente": ATRIBUCION,
        "fecha": date.today().isoformat(),
        "osmnx": ox.__version__,
        "centro": zona["centro"],
        "radio_m": zona["radio_m"],
        "nodos": len(nodos),
        "aristas": len(aristas),
        "nota": "Aristas dirigidas [i, j, minutos]; tiempos estimados sin tráfico. Generado por scripts/descargar_red.py.",
    }
    with open(ARCHIVO_RED, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"meta": meta, "nodos": nodos, "aristas": aristas}, f, separators=(",", ":"), ensure_ascii=False)
    return ARCHIVO_RED.stat().st_size / 1_000_000


def asignar_establecimientos(nodos: list) -> dict[str, tuple[int, float]]:
    """Paso 5: agrega "nodo" y "distancia_nodo_m" a cada establecimiento de grafo.json.
    Se edita el texto (una línea por establecimiento) para no alterar el formato del archivo."""
    ruta = DATA / "grafo.json"
    with open(ruta, encoding="utf-8", newline="") as f:             # newline="": no traducir los saltos de línea
        texto = f.read()
    original = json.loads(texto)
    asignados: dict[str, tuple[int, float]] = {}
    for eid, e in original["establecimientos"].items():
        nodo, d = red_vial.nodo_mas_cercano(e["lat"], e["lng"], nodos)
        asignados[eid] = (nodo, round(d, 1))
        patron = re.compile(rf'^(\s*"{re.escape(eid)}":\s*\{{[^{{}}]*?)(?:,\s*"nodo":\s*\d+,\s*"distancia_nodo_m":\s*[\d.]+)?'
                            r'(\}\s*,?\s*)$', re.M)
        texto, n = patron.subn(lambda m, a=asignados[eid]: f'{m.group(1)}, "nodo": {a[0]}, "distancia_nodo_m": {a[1]}{m.group(2)}',
                               texto)
        if n != 1:
            raise SystemExit(f"No pude editar la línea del establecimiento {eid} en grafo.json")
    nuevo = json.loads(texto)    # comprobación: sigue siendo JSON y no cambió nada más (salvo "nodo" y "distancia_nodo_m")
    def sin_nodo(e):
        return {k: v for k, v in e.items() if k not in ("nodo", "distancia_nodo_m")}
    for eid, e in nuevo["establecimientos"].items():
        assert sin_nodo(e) == sin_nodo(original["establecimientos"][eid]), eid
    assert {k: v for k, v in nuevo.items() if k != "establecimientos"} == {k: v for k, v in original.items() if k != "establecimientos"}
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:     # el repo usa LF; en Windows write_text daría CRLF
        f.write(texto)
    return asignados


def _texto(valor) -> str | None:
    return None if valor is None or pd.isna(valor) else str(valor)


def guardar_candidatos(centro: tuple[float, float], zona: dict, nodos: list) -> int:
    """Paso 6: hospitales y clínicas de OSM dentro de la zona, SIN agregarlos a grafo.json."""
    print("Descargando hospitales y clínicas de OSM…")
    gdf = ox.features_from_point(centro, tags={"amenity": ["hospital", "clinic"]}, dist=zona["radio_m"])
    candidatos = []
    for (elemento, osm_id), fila in gdf.iterrows():
        geom = fila.geometry
        punto = geom if geom.geom_type == "Point" else geom.representative_point()
        lat, lng = round(punto.y, 6), round(punto.x, 6)
        if red_vial.haversine(centro, (lat, lng)) > zona["radio_m"]:
            continue   # el cuadrado descargado es mayor que el círculo de cobertura
        nodo, d = red_vial.nodo_mas_cercano(lat, lng, nodos)
        calle, numero = _texto(fila.get("addr:street")), _texto(fila.get("addr:housenumber"))
        candidatos.append({
            "nombre": _texto(fila.get("name")) or "(sin nombre en OSM)",
            "tipo_osm": _texto(fila.get("amenity")),
            "lat": lat, "lng": lng,
            "direccion": " ".join(x for x in (calle, numero) if x) or None,
            "telefono": _texto(fila.get("phone")) or _texto(fila.get("contact:phone")),
            "osm_id": f"{elemento}/{osm_id}",
            "nodo": nodo, "distancia_nodo_m": round(d, 1),
            "revisar": True,
        })
    candidatos.sort(key=lambda c: (c["nombre"], c["osm_id"]))
    with open(ARCHIVO_CANDIDATOS, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "_nota": "Candidatos de OpenStreetMap, SIN validar. No están en grafo.json: el equipo los contrasta con RENIPRESS (T6) "
                     "y solo entonces los agrega. Generado por scripts/descargar_red.py.",
            "fuente": ATRIBUCION,
            "establecimientos": candidatos,
        }, f, ensure_ascii=False, indent=1)
    return len(candidatos)


def verificar_cobertura(zona: dict, nodos: list) -> list[str]:
    """La zona debe cubrir, como mínimo, los puntos de control de zona.json."""
    problemas = []
    for p in zona["puntos_de_control"]:
        if red_vial.haversine((zona["centro"]["lat"], zona["centro"]["lng"]), (p["lat"], p["lng"])) > zona["radio_m"]:
            problemas.append(f"{p['nombre']}: fuera del radio")
            continue
        _, d = red_vial.nodo_mas_cercano(p["lat"], p["lng"], nodos)
        if d > zona["umbral_fuera_de_zona_m"]:
            problemas.append(f"{p['nombre']}: la calle más cercana está a {d:.0f} m (umbral {zona['umbral_fuera_de_zona_m']} m)")
    return problemas


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--overpass", help="URL de otro servidor Overpass si el principal está saturado (p. ej. https://overpass.private.coffee/api)")
    ap.add_argument("--reintentos", type=int, default=4)
    ap.add_argument("--solo-asignar", action="store_true",
                    help="no descarga nada: reasigna el nodo de cada establecimiento de grafo.json con la red ya guardada "
                         "(para cuando el equipo agrega o corrige establecimientos, tarea T6)")
    args = ap.parse_args()

    if args.solo_asignar:
        nodos = json.loads(ARCHIVO_RED.read_text(encoding="utf-8"))["nodos"]
        for eid, (nodo, d) in asignar_establecimientos(nodos).items():
            print(f"{eid}: nodo {nodo} a {d} m")
        return 0

    ox.settings.http_user_agent = "TriajeLogico-descarga-red/1.0 (proyecto academico)"
    ox.settings.requests_timeout = 300
    ox.settings.cache_folder = str(RAIZ / ".cache_osmnx")
    if args.overpass:
        ox.settings.overpass_url = args.overpass.rstrip("/")

    zona = json.loads((DATA / "zona.json").read_text(encoding="utf-8"))
    centro = (zona["centro"]["lat"], zona["centro"]["lng"])
    inicio = time.time()

    G = con_reintentos(lambda: descargar_grafo(centro, zona["radio_m"]), args.reintentos, 30)
    nodos, aristas = compactar(G)
    mb = guardar_red(nodos, aristas, zona)
    asignados = asignar_establecimientos(nodos)
    try:
        n_candidatos = con_reintentos(lambda: guardar_candidatos(centro, zona, nodos), args.reintentos, 30)
    except Exception as e:  # noqa: BLE001  (la red ya quedó guardada; los candidatos se pueden repetir)
        n_candidatos = None
        print(f"  no se pudieron descargar los candidatos ({type(e).__name__}); la red sí quedó guardada. Repite el script.")
    problemas = verificar_cobertura(zona, nodos)

    print("\n=== Resumen ===")
    print(f"Nodos:  {miles(len(nodos))}")
    print(f"Aristas: {miles(len(aristas))} (dirigidas)")
    print(f"Tamaño de data/red_lima.json: {mb:.1f} MB" + ("   ⚠ más de 40 MB: reduce el radio antes de subirlo a GitHub" if mb > 40 else ""))
    print(f"Establecimientos de grafo.json asignados a su nodo: {len(asignados)}")
    for eid, (nodo, d) in asignados.items():
        print(f"   {eid}: nodo {nodo} a {d} m")
    if n_candidatos is not None:
        print(f"Candidatos OSM (hospitales y clínicas, sin validar): {n_candidatos} → {ARCHIVO_CANDIDATOS.name}")
    print(f"Puntos de control cubiertos: {len(zona['puntos_de_control']) - len(problemas)}/{len(zona['puntos_de_control'])}")
    for p in problemas:
        print("   ✗", p)
    print(f"Tiempo: {time.time() - inicio:.0f} s")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
