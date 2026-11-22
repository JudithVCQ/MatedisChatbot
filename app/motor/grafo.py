"""Grafo de distritos de Lima y Dijkstra (implementación propia).

Es el RESPALDO cuando no existe data/red_lima.json: la ruta por calles de verdad vive en
app/motor/red_vial.py y se elige en app/motor/ruteo.py.
"""
import heapq

from app.datos import cargar, niveles
from app.motor import red_vial

VELOCIDAD_URBANA_KMH = 30.0   # velocidad urbana estimada (modelo): minutos = km / velocidad * 60
VECINOS_USUARIO = 3           # distritos a los que se une el vértice temporal "u"
USUARIO = "u"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia en km entre dos puntos (usa el haversine propio de red_vial)."""
    return red_vial.haversine((lat1, lng1), (lat2, lng2)) / 1000


def construir(g: dict | None = None) -> dict[str, list[tuple[str, int]]]:
    g = g or cargar("grafo")
    adj: dict[str, list[tuple[str, int]]] = {d: [] for d in g["distritos"]}
    for a, b, w in g["vias"]:
        adj[a].append((b, w))
        adj[b].append((a, w))
    for eid, e in g["establecimientos"].items():
        adj[eid] = [(e["distrito"], e["minutos"])]
        adj[e["distrito"]].append((eid, e["minutos"]))
    return adj


def dijkstra(adj: dict, origen: str) -> tuple[dict[str, float], dict[str, str | None]]:
    dist = {v: float("inf") for v in adj}
    prev: dict[str, str | None] = {v: None for v in adj}
    dist[origen] = 0
    cola = [(0, origen)]
    while cola:
        d, u = heapq.heappop(cola)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                prev[v] = u
                heapq.heappush(cola, (dist[v], v))
    return dist, prev


# Respaldo TRANSITORIO para establecimientos sin 'categoria' (datos de ejemplo; ver T6).
# Se elimina cuando todos los establecimientos de grafo.json traigan categoria y emergencia_24h.
TIPO_SIN_CATEGORIA = {"urgencia_alta": "hospital", "urgencia_media": "centro_salud", "urgencia_baja": "centro_salud"}


def aceptable(establecimiento: dict, nivel: str, definiciones: dict | None = None) -> bool:
    """¿Sirve este establecimiento para el nivel de urgencia? Lo define data/niveles.json:
    la categoría debe estar entre las aceptadas y, si el nivel lo exige, tener emergencia 24 h."""
    n = (definiciones or niveles())[nivel]
    if "categoria" not in establecimiento:
        return establecimiento.get("tipo") == TIPO_SIN_CATEGORIA.get(nivel)
    if establecimiento["categoria"] not in n["categorias"]:
        return False
    return bool(establecimiento.get("emergencia_24h")) or not n.get("requiere_emergencia_24h")


def _ruta(adj: dict, origen: str, nivel: str, punto_origen: dict | None = None,
          permitidos: set[str] | None = None) -> dict | None:
    """Dijkstra desde `origen` hasta el establecimiento aceptable más cercano para el nivel
    (y, si se indica, solo entre los `permitidos`, p. ej. los que cubre el seguro del usuario)."""
    g = cargar("grafo")
    destinos = [e for e, d in g["establecimientos"].items()
                if aceptable(d, nivel) and (permitidos is None or e in permitidos)]
    if not destinos:
        return None
    dist, prev = dijkstra(adj, origen)
    destino = min(destinos, key=lambda e: dist[e])
    if dist[destino] == float("inf"):
        return None
    camino, v = [], destino
    while v is not None:
        camino.append(v)
        v = prev[v]
    camino.reverse()

    def punto(n):
        if n == USUARIO:
            return punto_origen
        d = g["distritos"].get(n) or g["establecimientos"][n]
        return {"nombre": d["nombre"], "lat": d["lat"], "lng": d["lng"]}

    return {"id": destino,
            "destino": g["establecimientos"][destino]["nombre"],
            "minutos": int(round(dist[destino])),
            "puntos": [punto(n) for n in camino]}    # el camino completo por distritos; ruteo.py lo adapta al contrato


def ruta_mas_corta(origen: str, nivel: str) -> dict | None:
    """Ruta mínima desde un distrito al establecimiento aceptable más cercano para el nivel de urgencia."""
    if origen not in cargar("grafo")["distritos"]:
        return None
    return _ruta(construir(), origen, nivel)


def ruta_desde_ubicacion(lat: float, lng: float, nivel: str,
                         permitidos: set[str] | None = None) -> tuple[dict | None, list[str]]:
    """Ruta desde la ubicación del usuario, que entra al grafo como vértice temporal "u".

    "u" se une a los 3 distritos más cercanos (haversine); peso = distancia / velocidad urbana,
    en minutos. El vértice vive solo en la lista de adyacencia local: grafo.json no se modifica.
    Devuelve (ruta, nombres de distritos conectados); (None, []) si el punto está fuera del círculo
    de cobertura de data/zona.json. Las coordenadas no se guardan ni se registran en ningún lado.
    """
    g = cargar("grafo")
    if not red_vial.en_zona(lat, lng):
        return None, []

    cercanos = sorted(((haversine_km(lat, lng, d["lat"], d["lng"]), k) for k, d in g["distritos"].items()))
    cercanos = cercanos[:VECINOS_USUARIO]

    adj = construir()   # copia nueva en cada llamada
    adj[USUARIO] = []
    for km, d in cercanos:
        minutos = km / VELOCIDAD_URBANA_KMH * 60
        adj[USUARIO].append((d, minutos))
        adj[d].append((USUARIO, minutos))

    ruta = _ruta(adj, USUARIO, nivel, {"nombre": "Tu ubicación", "lat": lat, "lng": lng}, permitidos)
    return ruta, [g["distritos"][d]["nombre"] for _, d in cercanos]


def grafo_completo() -> dict:
    """Todos los nodos y aristas del modelo de distritos (GET /api/grafo)."""
    g = cargar("grafo")
    nodos = [{"id": k, "nombre": v["nombre"], "tipo": "distrito", "lat": v["lat"], "lng": v["lng"]}
             for k, v in g["distritos"].items()]
    nodos += [{"id": k, "nombre": v["nombre"], "tipo": v["tipo"], "lat": v["lat"], "lng": v["lng"]}
              for k, v in g["establecimientos"].items()]
    aristas = [{"origen": a, "destino": b, "minutos": w} for a, b, w in g["vias"]]
    aristas += [{"origen": v["distrito"], "destino": k, "minutos": v["minutos"]}
                for k, v in g["establecimientos"].items()]
    return {"nodos": nodos, "aristas": aristas}
