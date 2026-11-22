"""Planifica la ruta al establecimiento adecuado, según el nivel de urgencia, el seguro y la ubicación.

Destinos = (establecimientos aceptados por el nivel, según data/niveles.json)
         ∩ (establecimientos que cubre el seguro: seguro → institución → establecimiento, en relaciones.py).
En urgencia ALTA no se filtra por seguro: toda emergencia se atiende en cualquier establecimiento (Ley 27604).
Si la intersección es vacía se usan las instituciones de respaldo (MINSA/GORE) y se explica.

Origen de la ruta: solo la ubicación del usuario (lat/lng). El camino lo calcula nuestro Dijkstra sobre la red de
calles de OpenStreetMap (red_vial.py); si data/red_lima.json no existe, sobre el grafo de distritos (grafo.py).
Sin ubicación, o fuera de la zona de data/zona.json, no hay ruta: se devuelve la recomendación (lista de destinos).

Privacidad (Ley 29733): las coordenadas se usan solo aquí, para calcular. Ni la traza ni el log las incluyen.
"""
from app.datos import cargar, niveles, zona
from app.motor import grafo, red_vial, relaciones, seguros


def miles(n: int) -> str:
    """52310 → '52.310' (separador de miles al estilo peruano)."""
    return f"{n:,}".replace(",", ".")


def establecimientos_del_nivel(nivel: str) -> dict[str, dict]:
    return {eid: e for eid, e in cargar("grafo")["establecimientos"].items() if grafo.aceptable(e, nivel)}


def _resultado(ruta=None, fuera=False, traza=None, establecimientos=None, explicacion="", nota=None) -> dict:
    return {"ruta": ruta, "fuera_de_zona": fuera, "traza": traza or [], "establecimientos": establecimientos or [],
            "explicacion": explicacion, "nota": nota}


def _ficha(e: dict) -> dict:
    return {"nombre": e["nombre"], "direccion": e.get("direccion"), "telefono": e.get("telefono"),
            "lat": e["lat"], "lng": e["lng"]}


def elegir_destinos(nivel: str, seguro: str | None) -> tuple[dict[str, dict], list[str], str, str | None]:
    """Devuelve (destinos, líneas de traza, explicación para el usuario, nota del seguro)."""
    aceptables = establecimientos_del_nivel(nivel)
    if niveles()[nivel].get("requiere_emergencia_24h"):
        return aceptables, ["Urgencia alta: emergencia 24 h más cercana de cualquier institución; "
                            "no se filtra por seguro (Ley 27604)"], "", None
    if seguro is None:
        return aceptables, ["Sin seguro indicado: se consideran todos los establecimientos del nivel"], "", None

    ids, linea = relaciones.destinos_por_seguro(seguro, set(aceptables))
    traza, nota = [linea], seguros.nota(seguro)
    if ids:
        return {i: aceptables[i] for i in ids}, traza, "", nota

    respaldo = cargar("seguros")["respaldo_instituciones"]
    nombres = "/".join(respaldo)
    ids = [e for e in relaciones.cubiertos_por_instituciones(respaldo) if e in aceptables]
    if ids:
        traza.append(f"Intersección vacía en la zona: se usa el respaldo {nombres} → {ids}")
        return ({i: aceptables[i] for i in ids}, traza,
                f"No encontré establecimientos de {seguros.etiqueta(seguro)} para este caso en la zona; "
                f"te indico los de {nombres}.", nota)
    traza.append(f"Intersección vacía y tampoco hay {nombres} para este nivel: se consideran todos los del nivel")
    return (aceptables, traza, f"No encontré establecimientos de {seguros.etiqueta(seguro)} ni de {nombres} para este "
                               "caso; te indico los disponibles.", nota)


def _ruta_por_calles(red: red_vial.Red, destinos: dict, origen: tuple[float, float]) -> dict | None:
    """Ruta por calles. Devuelve None si ningún destino tiene nodo asignado (datos sin actualizar)."""
    z = zona()
    traza: list[str] = []
    if not red_vial.en_zona(*origen):
        traza.append("Ubicación fuera del círculo de cobertura: no se calculó ruta")
        return _resultado(fuera=True, traza=traza)

    nodo, metros = red_vial.nodo_mas_cercano(*origen, red.nodos)
    if metros > z["umbral_fuera_de_zona_m"]:
        traza.append(f"La calle más cercana está a {round(metros)} m (umbral {z['umbral_fuera_de_zona_m']} m): no se calculó ruta")
        return _resultado(fuera=True, traza=traza)

    por_nodo: dict[int, list[str]] = {}
    for eid, e in destinos.items():
        if isinstance(e.get("nodo"), int) and 0 <= e["nodo"] < len(red.nodos):
            por_nodo.setdefault(e["nodo"], []).append(eid)
    if not por_nodo:
        return None

    hallado = red_vial.dijkstra_hasta(nodo, por_nodo, red.adj)
    if hallado is None:
        traza.append("No hay camino por calles hasta ningún establecimiento del nivel")
        return _resultado(traza=traza)
    nodo_destino, minutos, camino = hallado
    eid = min(por_nodo[nodo_destino], key=lambda x: (destinos[x].get("distancia_nodo_m", 0), x))
    e = destinos[eid]
    minutos_aprox = max(1, round(minutos))

    linea = [list(origen)] + [list(red.nodos[n]) for n in camino] + [[e["lat"], e["lng"]]]
    ruta = {
        "destino": e["nombre"], "minutos": minutos_aprox, "linea": linea,
        "puntos": [{"nombre": "Tu ubicación", "lat": origen[0], "lng": origen[1]},
                   {"nombre": e["nombre"], "lat": e["lat"], "lng": e["lng"]}],
        "direccion": e.get("direccion"), "telefono": e.get("telefono"),
    }
    traza.append(f"Origen: esquina más cercana a tu ubicación (a {round(metros)} m) → "
                 f"Dijkstra sobre {miles(len(red.nodos))} nodos → {e['nombre']}, {minutos_aprox} min")
    return _resultado(ruta=ruta, traza=traza)


def _adaptar_distritos(ruta: dict) -> dict:
    """El grafo de distritos devuelve el camino por distritos; el contrato pide la línea y solo origen y destino."""
    puntos = ruta["puntos"]
    e = cargar("grafo")["establecimientos"][ruta["id"]]
    return {"destino": ruta["destino"], "minutos": ruta["minutos"],
            "linea": [[p["lat"], p["lng"]] for p in puntos],
            "puntos": [puntos[0], puntos[-1]],
            "direccion": e.get("direccion"), "telefono": e.get("telefono")}


def _respaldo_por_distritos(nivel: str, lat: float, lng: float, destinos: dict) -> dict:
    """Sin red de calles: ruta desde la ubicación sobre el grafo de distritos (vértice temporal "u")."""
    if not red_vial.en_zona(lat, lng):
        return _resultado(fuera=True, traza=["Ubicación fuera del círculo de cobertura: no se calculó ruta"])
    ruta, conectados = grafo.ruta_desde_ubicacion(lat, lng, nivel, set(destinos))
    if ruta is None:
        return _resultado(traza=["No hay establecimientos para el nivel de urgencia"])
    traza = [f"Ubicación → vértice u conectado a {', '.join(conectados)} → Dijkstra → "
             f"{ruta['destino']} ({ruta['minutos']} min)"]
    return _resultado(ruta=_adaptar_distritos(ruta), traza=traza)


def planificar(nivel: str, lat: float | None, lng: float | None, seguro: str | None = None) -> dict:
    """Devuelve {"ruta", "fuera_de_zona", "traza", "establecimientos", "explicacion", "nota"}.

    `ruta` es None si no hay ruta; entonces `establecimientos` trae la recomendación (los destinos)."""
    destinos, traza, explicacion, nota = elegir_destinos(nivel, seguro)
    if not destinos:
        return _resultado(traza=traza + ["No hay establecimientos para el nivel de urgencia"])
    recomendacion = sorted((_ficha(e) for e in destinos.values()), key=lambda f: f["nombre"])

    if lat is None or lng is None:
        return _resultado(traza=traza + ["Sin ubicación: no se calculó ruta"], establecimientos=recomendacion,
                          explicacion=explicacion, nota=nota)

    red = red_vial.cargar_red()
    resultado = _ruta_por_calles(red, destinos, (lat, lng)) if red else None
    if resultado is None:
        resultado = _respaldo_por_distritos(nivel, lat, lng, destinos)
    resultado["traza"] = traza + resultado["traza"]
    resultado["explicacion"], resultado["nota"] = explicacion, nota
    if resultado["ruta"] is None:
        resultado["establecimientos"] = recomendacion
    return resultado
