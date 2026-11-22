"""Red vial real de Lima (OpenStreetMap): esquinas y calles como grafo dirigido.

data/red_lima.json lo genera scripts/descargar_red.py (una sola vez, en la PC; no en Render).
Aquí solo se lee y se usa. Todo el cálculo es propio, sin librerías de grafos:

  - haversine: distancia sobre la esfera entre dos puntos;
  - nodo_mas_cercano: ajusta un punto cualquiera a la esquina más próxima;
  - dijkstra_hasta: camino de menor tiempo hasta el más cercano de varios objetivos.

Los nodos se identifican por su índice en la lista; las aristas son DIRIGIDAS para respetar
los sentidos de las calles. Si el archivo no existe, cargar_red() devuelve None y el sistema
usa el grafo de distritos (app/motor/grafo.py).
"""
import heapq
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt

from app.datos import DATA, zona

log = logging.getLogger("triaje.red")
ARCHIVO_RED = DATA / "red_lima.json"
RADIO_TIERRA_M = 6371000.0


@dataclass(frozen=True)
class Red:
    nodos: list[tuple[float, float]]        # índice = id del nodo; (lat, lng)
    adj: list[list[tuple[int, float]]]      # dirigida: adj[i] = [(j, minutos), ...]
    meta: dict


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distancia en metros entre a=(lat, lng) y b=(lat, lng) por la fórmula del haversine."""
    (lat1, lng1), (lat2, lng2) = a, b
    f1, f2 = radians(lat1), radians(lat2)
    h = sin((f2 - f1) / 2) ** 2 + cos(f1) * cos(f2) * sin(radians(lng2 - lng1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * asin(min(1.0, sqrt(h)))


def construir_red(nodos: list, aristas: list, meta: dict | None = None) -> Red:
    """Arma la lista de adyacencia dirigida a partir de [lat, lng] y [i, j, minutos]."""
    adj: list[list[tuple[int, float]]] = [[] for _ in nodos]
    for i, j, minutos in aristas:
        adj[i].append((j, minutos))
    return Red([(lat, lng) for lat, lng in nodos], adj, meta or {})


@lru_cache
def cargar_red() -> Red | None:
    """Lee red_lima.json UNA sola vez. Devuelve None si no existe (o no se puede leer): no es un error."""
    if not ARCHIVO_RED.exists():
        return None
    try:
        with open(ARCHIVO_RED, encoding="utf-8") as f:
            d = json.load(f)
        return construir_red(d["nodos"], d["aristas"], d.get("meta"))
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        log.warning("red_lima.json no se pudo leer; se usa el grafo de distritos: %s", e)
        return None


def en_zona(lat: float, lng: float) -> bool:
    """¿Está el punto dentro del círculo de cobertura de data/zona.json?"""
    z = zona()
    return haversine((z["centro"]["lat"], z["centro"]["lng"]), (lat, lng)) <= z["radio_m"]


def nodo_mas_cercano(lat: float, lng: float, nodos: list | None = None) -> tuple[int, float]:
    """Esquina más cercana a (lat, lng): búsqueda lineal con haversine. Devuelve (nodo, distancia_m)."""
    if nodos is None:
        red = cargar_red()
        if red is None:
            raise RuntimeError("No hay red vial cargada")
        nodos = red.nodos
    punto = (lat, lng)
    mejor, mejor_d = -1, float("inf")
    for i, nodo in enumerate(nodos):
        d = haversine(punto, nodo)
        if d < mejor_d:
            mejor, mejor_d = i, d
    return mejor, mejor_d


def _dijkstra(adj: list, origen: int, objetivos: set | None = None):
    """Dijkstra con cola de prioridad. Si hay objetivos, se detiene al sacar el primero de la cola.

    PARADA TEMPRANA: con pesos no negativos, cuando un nodo sale de la cola su distancia ya es
    definitiva (los demás nodos de la cola tienen distancia provisional ≥ la suya, y sumar aristas
    solo la aumenta). Los nodos salen de la cola en orden no decreciente de distancia, así que el
    PRIMER objetivo que sale es el de menor distancia entre todos los objetivos: cualquier otro
    objetivo saldría después, con distancia ≥. Detenerse ahí da el mismo resultado que el Dijkstra
    completo, sin recorrer el resto de la red.
    """
    dist: dict[int, float] = {origen: 0.0}
    previo: dict[int, int] = {}
    cola = [(0.0, origen)]
    cerrados: set[int] = set()
    while cola:
        d, u = heapq.heappop(cola)
        if u in cerrados:
            continue
        if objetivos and u in objetivos:
            return dist, previo, u
        cerrados.add(u)
        for v, minutos in adj[u]:
            nueva = d + minutos
            if nueva < dist.get(v, float("inf")):
                dist[v] = nueva
                previo[v] = u
                heapq.heappush(cola, (nueva, v))
    return dist, previo, None


def dijkstra_completo(adj: list, origen: int) -> tuple[dict[int, float], dict[int, int]]:
    """Dijkstra sin parada temprana (referencia para verificar dijkstra_hasta)."""
    dist, previo, _ = _dijkstra(adj, origen)
    return dist, previo


def dijkstra_hasta(origen: int, objetivos, adj: list | None = None) -> tuple[int, float, list[int]] | None:
    """Camino de menor tiempo desde `origen` hasta el objetivo más cercano.

    Devuelve (objetivo, minutos, camino con los nodos de origen a objetivo) o None si ninguno es alcanzable.
    `adj` es la lista de adyacencia dirigida; por defecto, la de la red real.
    """
    objetivos = set(objetivos)
    if not objetivos:
        return None
    if adj is None:
        red = cargar_red()
        if red is None:
            raise RuntimeError("No hay red vial cargada")
        adj = red.adj
    dist, previo, hallado = _dijkstra(adj, origen, objetivos)
    if hallado is None:
        return None
    camino = [hallado]
    while camino[-1] != origen:
        camino.append(previo[camino[-1]])
    camino.reverse()
    return hallado, dist[hallado], camino
