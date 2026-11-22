"""Red vial: algoritmos sobre una red hecha a mano (sin depender del archivo real) y pruebas con la red real.

Las pruebas "con la red real" se saltan si data/red_lima.json no existe (python scripts/descargar_red.py).
"""
import json
import random
import re
import time

import pytest

from app import datos
from app.motor import red_vial, ruteo
from tests.ayudas import (AREQUIPA, KENNEDY, MAR_DENTRO_DEL_CIRCULO, NO_RUTA, SAN_JUAN_DE_MIRAFLORES, UNMSM, cliente, etiquetas,
                          emergencia, enviar, hasta_conclusion, nueva, ruta_de_emergencia, tiene_accion)

con_red = pytest.mark.skipif(not red_vial.ARCHIVO_RED.exists(),
                             reason="data/red_lima.json no existe (python scripts/descargar_red.py)")
FUERA = "Estás fuera de la zona cubierta. " + NO_RUTA


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


@pytest.fixture
def sin_red(monkeypatch):
    """Simula que red_lima.json no existe: se usa el grafo de distritos."""
    monkeypatch.setattr(red_vial, "cargar_red", lambda: None)


# ---------- red hecha a mano ----------
# Nodos 0..4 cerca de Lima. Aristas dirigidas [origen, destino, minutos]:
#   0 → 1 (UN SOLO SENTIDO), 1 → 2, 2 → 0 (vuelta larga), 2 ↔ 3, 0 ↔ 3, y el nodo 4 sin salidas.
NODOS = [[-12.050, -77.040], [-12.050, -77.030], [-12.060, -77.030], [-12.060, -77.040], [-12.070, -77.050]]
ARISTAS = [[0, 1, 1.0], [1, 2, 1.0], [2, 0, 10.0], [2, 3, 1.0], [3, 2, 1.0], [0, 3, 5.0], [3, 0, 5.0], [3, 4, 2.0]]
RED = red_vial.construir_red(NODOS, ARISTAS)


def pasos_validos(camino, adj):
    """Cada paso del camino existe como arista dirigida; devuelve el tiempo total."""
    total = 0.0
    for a, b in zip(camino, camino[1:]):
        pesos = [w for v, w in adj[a] if v == b]
        assert pesos, f"no existe la arista dirigida {a} → {b}"
        total += min(pesos)
    return total


def test_dijkstra_respeta_la_calle_de_un_solo_sentido():
    objetivo, minutos, camino = red_vial.dijkstra_hasta(0, {1}, RED.adj)
    assert (objetivo, minutos, camino) == (1, 1.0, [0, 1])
    # de 1 a 0 NO se puede ir "de vuelta" por la calle de un sentido: se rodea 1 → 2 → 3 → 0
    objetivo, minutos, camino = red_vial.dijkstra_hasta(1, {0}, RED.adj)
    assert (objetivo, camino) == (0, [1, 2, 3, 0]) and minutos == 7.0
    assert pasos_validos(camino, RED.adj) == minutos


def test_dijkstra_elige_el_objetivo_mas_cercano_y_casos_borde():
    assert red_vial.dijkstra_hasta(0, {2, 3}, RED.adj)[:2] == (2, 2.0)     # 0→1→2 (2) gana a 0→3 (5)
    assert red_vial.dijkstra_hasta(0, {0}, RED.adj) == (0, 0.0, [0])       # el origen ya es objetivo
    assert red_vial.dijkstra_hasta(4, {0}, RED.adj) is None                # el nodo 4 no tiene salidas
    assert red_vial.dijkstra_hasta(0, set(), RED.adj) is None


def _red_aleatoria(semilla, n=60, m=240):
    azar = random.Random(semilla)
    adj = [[] for _ in range(n)]
    for _ in range(m):
        a, b = azar.randrange(n), azar.randrange(n)
        if a != b:
            adj[a].append((b, round(azar.uniform(0.1, 10), 3)))
    return adj, azar


@pytest.mark.parametrize("semilla", range(40))
def test_parada_temprana_igual_al_dijkstra_completo(semilla):
    adj, azar = _red_aleatoria(semilla)
    for _ in range(10):
        origen = azar.randrange(len(adj))
        objetivos = {azar.randrange(len(adj)) for _ in range(azar.randint(1, 5))}
        dist, _ = red_vial.dijkstra_completo(adj, origen)
        alcanzables = [t for t in objetivos if t in dist]
        resultado = red_vial.dijkstra_hasta(origen, objetivos, adj)
        if not alcanzables:
            assert resultado is None
            continue
        objetivo, minutos, camino = resultado
        assert minutos == pytest.approx(min(dist[t] for t in alcanzables))       # mismo tiempo mínimo
        assert objetivo in objetivos and dist[objetivo] == pytest.approx(minutos)
        assert camino[0] == origen and camino[-1] == objetivo
        assert pasos_validos(camino, adj) == pytest.approx(minutos)              # y el camino es real


def test_haversine_con_puntos_conocidos():
    assert red_vial.haversine((0, 0), (0, 1)) == pytest.approx(111194.93, abs=1)         # 1° de longitud en el ecuador
    assert red_vial.haversine((0, 0), (1, 0)) == pytest.approx(111194.93, abs=1)         # 1° de latitud
    assert red_vial.haversine((-12.05, -77.04), (-12.05, -77.04)) == 0
    plaza_san_martin, parque_kennedy = (-12.0519, -77.0343), (-12.1211, -77.0297)
    d = red_vial.haversine(plaza_san_martin, parque_kennedy)
    assert d == pytest.approx(7711, abs=10)                                              # ~7,7 km calculados a mano
    assert d == red_vial.haversine(parque_kennedy, plaza_san_martin)                     # simétrica
    assert red_vial.haversine((90, 0), (-90, 0)) == pytest.approx(20015087, abs=10)      # polo a polo, sin error de dominio


def test_nodo_mas_cercano_en_la_red_a_mano():
    nodo, metros = red_vial.nodo_mas_cercano(-12.0601, -77.0299, RED.nodos)
    assert nodo == 2 and metros < 20
    nodo, metros = red_vial.nodo_mas_cercano(-12.0701, -77.0501, RED.nodos)
    assert nodo == 4


def test_miles_al_estilo_peruano():
    assert ruteo.miles(52310) == "52.310" and ruteo.miles(999) == "999" and ruteo.miles(1234567) == "1.234.567"


def test_cargar_red_sin_archivo_o_corrupto_no_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(red_vial, "ARCHIVO_RED", tmp_path / "no_existe.json")
    red_vial.cargar_red.cache_clear()
    try:
        assert red_vial.cargar_red() is None
        (tmp_path / "roto.json").write_text("{ esto no es json", encoding="utf-8")
        monkeypatch.setattr(red_vial, "ARCHIVO_RED", tmp_path / "roto.json")
        red_vial.cargar_red.cache_clear()
        assert red_vial.cargar_red() is None
        (tmp_path / "ok.json").write_text(json.dumps({"nodos": NODOS, "aristas": ARISTAS}), encoding="utf-8")
        monkeypatch.setattr(red_vial, "ARCHIVO_RED", tmp_path / "ok.json")
        red_vial.cargar_red.cache_clear()
        assert len(red_vial.cargar_red().nodos) == 5 and red_vial.cargar_red().adj[0] == [(1, 1.0), (3, 5.0)]
    finally:
        monkeypatch.undo()
        red_vial.cargar_red.cache_clear()


def test_zona_se_lee_de_zona_json():
    z = datos.zona()
    assert (z["centro"], z["radio_m"], z["umbral_fuera_de_zona_m"]) == ({"lat": -12.070, "lng": -77.050}, 9000, 1500)
    assert red_vial.en_zona(z["centro"]["lat"], z["centro"]["lng"])
    assert red_vial.en_zona(*UNMSM) and not red_vial.en_zona(*SAN_JUAN_DE_MIRAFLORES)
    assert cliente.get("/api/zona").json() == {"centro": z["centro"], "radio_m": z["radio_m"]}
    assert {p["nombre"] for p in z["puntos_de_control"]} >= {"Ciudad Universitaria de la UNMSM", "Cercado de Lima", "Breña",
                                                             "Rímac", "San Martín de Porres", "Jesús María", "Pueblo Libre",
                                                             "San Miguel", "Lince", "La Victoria", "San Isidro", "Surquillo",
                                                             "Miraflores"}
    assert all(red_vial.en_zona(p["lat"], p["lng"]) for p in z["puntos_de_control"])


# ---------- con la red real ----------
@con_red
def test_la_zona_cubre_los_puntos_de_control():
    z = datos.zona()
    for p in z["puntos_de_control"]:
        _, metros = red_vial.nodo_mas_cercano(p["lat"], p["lng"])
        assert metros <= z["umbral_fuera_de_zona_m"], f"{p['nombre']}: calle más cercana a {metros:.0f} m"


@con_red
def test_establecimientos_asignados_a_su_nodo_y_cerca_de_su_calle():
    red = red_vial.cargar_red()
    maximo = datos.zona()["max_distancia_establecimiento_nodo_m"]
    for eid, e in datos.cargar("grafo")["establecimientos"].items():
        assert 0 <= e["nodo"] < len(red.nodos), eid
        metros = red_vial.haversine((e["lat"], e["lng"]), red.nodos[e["nodo"]])
        assert metros == pytest.approx(e["distancia_nodo_m"], abs=1)
        assert metros <= maximo, f"{eid} está a {metros:.1f} m de su calle (máximo {maximo} m)"


@con_red
@pytest.mark.parametrize("punto", [UNMSM, KENNEDY])
def test_hay_ruta_por_calles(punto):
    d = ruta_de_emergencia(punto)
    ruta = d["ruta"]
    assert ruta is not None and not d["fuera_de_zona"] and d["urgencia"] == "urgencia_alta"
    assert ruta["minutos"] >= 1 and len(ruta["linea"]) >= 5                       # la línea sigue calles, no es un segmento
    assert [p["nombre"] for p in ruta["puntos"]][0] == "Tu ubicación" and len(ruta["puntos"]) == 2
    assert ruta["puntos"][1]["nombre"] == ruta["destino"]
    assert ruta["linea"][0] == [round(punto[0], 3), round(punto[1], 3)]            # empieza en el origen (redondeado)
    assert ruta["linea"][-1] == [ruta["puntos"][1]["lat"], ruta["puntos"][1]["lng"]]
    hospitales = {e["nombre"] for e in ruteo.establecimientos_del_nivel("urgencia_alta").values()}
    assert ruta["destino"] in hospitales


@con_red
def test_traza_del_origen_y_privacidad():
    d = ruta_de_emergencia(UNMSM)
    patron = r"Origen: esquina más cercana a tu ubicación \(a \d+ m\) → Dijkstra sobre \d+\.\d{3} nodos → .+, \d+ min"
    lineas = [l for l in d["traza"] if l.startswith("Origen:")]
    assert len(lineas) == 1 and re.fullmatch(patron, lineas[0])
    assert not re.search(r"-\d{2}\.\d", "\n".join(d["traza"]))                   # ninguna coordenada (-12.0…, -77.0…) en la traza


@con_red
def test_la_ruta_sigue_el_sentido_de_las_calles_en_la_red_real():
    red = red_vial.cargar_red()
    origen, _ = red_vial.nodo_mas_cercano(*UNMSM)
    destinos = {e["nodo"] for e in ruteo.establecimientos_del_nivel("urgencia_alta").values()}
    _, minutos, camino = red_vial.dijkstra_hasta(origen, destinos, red.adj)
    assert pasos_validos(camino, red.adj) == pytest.approx(minutos)


@con_red
@pytest.mark.parametrize("punto", [SAN_JUAN_DE_MIRAFLORES, AREQUIPA])
def test_fuera_de_zona_por_radio(punto):
    d = ruta_de_emergencia(punto)
    assert d["fuera_de_zona"] and d["ruta"] is None and FUERA in d["mensaje"]
    assert d["mensaje"].count("SAMU 106") == 1
    assert d["establecimientos"] and tiene_accion(d, "ubicacion")              # recomienda igual y ofrece reintentar


@con_red
def test_fuera_de_zona_por_umbral_dentro_del_circulo():
    assert red_vial.en_zona(*MAR_DENTRO_DEL_CIRCULO)           # el punto está dentro del radio...
    d = ruta_de_emergencia(MAR_DENTRO_DEL_CIRCULO)             # ...pero a más de 1500 m de toda calle
    assert d["fuera_de_zona"] and d["ruta"] is None and FUERA in d["mensaje"]
    assert any("calle más cercana" in l for l in d["traza"])


@con_red
def test_una_ruta_tarda_menos_de_un_segundo():
    red_vial.cargar_red()
    ruta_de_emergencia(UNMSM)                                   # calentamiento
    for punto in (UNMSM, KENNEDY):
        sesion = nueva()
        emergencia(sesion)
        inicio = time.perf_counter()
        d = enviar(sesion, "", punto=punto)
        segundos = time.perf_counter() - inicio
        assert d["ruta"] is not None and segundos < 1.0, f"{segundos:.2f} s"


# ---------- coordenadas corregidas con OSM ----------
def _candidato_osm(osm_id):
    cand = json.load(open(datos.DATA / "establecimientos_osm_candidatos.json", encoding="utf-8"))["establecimientos"]
    return next(c for c in cand if c["osm_id"] == osm_id)


def test_coordenadas_corregidas_coinciden_con_osm():
    corregidos = {k: e for k, e in datos.cargar("grafo")["establecimientos"].items() if e.get("coordenadas_fuente") == "OSM"}
    assert {"h_casimiro", "h_rebagliati", "h_loayza", "h_dos_de_mayo", "h_cayetano"} <= set(corregidos)
    for eid, e in corregidos.items():
        osm = _candidato_osm(e["osm_id"])
        assert (e["lat"], e["lng"]) == (osm["lat"], osm["lng"]), eid
        assert e["revisar"] is True
    assert all("coordenadas_fuente" not in e for k, e in datos.cargar("grafo")["establecimientos"].items() if "EJEMPLO" in e["nombre"])


@con_red
def test_ruta_al_casimiro_ulloa_termina_en_la_av_republica_de_panama():
    """El Casimiro Ulloa está sobre la Av. República de Panamá (en OSM figura como Av. Roosevelt 6355).
    Referencia: su coordenada de OSM. La última esquina de la ruta debe quedar a menos de 100 m de ella
    (con la coordenada antigua, varias cuadras al este, la ruta terminaba a más de 100 m)."""
    casimiro = datos.cargar("grafo")["establecimientos"]["h_casimiro"]
    referencia = (_candidato_osm(casimiro["osm_id"])["lat"], _candidato_osm(casimiro["osm_id"])["lng"])
    d = ruta_de_emergencia(KENNEDY)                              # desde Miraflores, la emergencia más cercana es el Casimiro
    ruta = d["ruta"]
    assert ruta["destino"] == casimiro["nombre"]
    ultima_esquina = tuple(ruta["linea"][-2])                    # [-1] es el establecimiento; [-2], la última esquina de la red
    assert red_vial.haversine(ultima_esquina, referencia) < 100
    assert casimiro["distancia_nodo_m"] < 100


@con_red
def test_la_coordenada_antigua_del_casimiro_no_cumplia():
    """Comprueba que la prueba anterior tiene sentido: el nodo que correspondía a la coordenada vieja estaba lejos de OSM."""
    red = red_vial.cargar_red()
    casimiro = datos.cargar("grafo")["establecimientos"]["h_casimiro"]
    referencia = (_candidato_osm(casimiro["osm_id"])["lat"], _candidato_osm(casimiro["osm_id"])["lng"])
    nodo_viejo, _ = red_vial.nodo_mas_cercano(-12.128, -77.016)   # la coordenada aproximada de antes
    assert red_vial.haversine(red.nodos[nodo_viejo], referencia) > 100


# ---------- sin importar la red ----------
@pytest.mark.parametrize("extra", [{"lat": 200, "lng": -77.0}, {"lat": -12.0, "lng": 181}, {"lat": -91, "lng": 0},
                                   {"lat": "abc", "lng": "xyz"}, {"lat": None, "lng": -77.0}, {"lat": -12.0}])
def test_coordenadas_invalidas_error_controlado(extra):
    r = cliente.post("/api/chat", json={"sesion": nueva(), "mensaje": "me duele el pecho", **extra})
    assert r.status_code == 422 and r.json()["estado"] == "ERROR" and r.json()["codigo"] == "ubicacion_invalida"
    assert "Traceback" not in r.text


def test_sin_ubicacion_recomienda_los_establecimientos_sin_ruta():
    sesion = nueva()
    emergencia(sesion)
    d = enviar(sesion, "", ubicacion_denegada=True)
    esperados = {e["nombre"] for e in ruteo.establecimientos_del_nivel("urgencia_alta").values()}
    assert d["ruta"] is None and not d["fuera_de_zona"] and NO_RUTA in d["mensaje"]
    assert {e["nombre"] for e in d["establecimientos"]} == esperados and esperados
    assert all(nombre in d["mensaje"] for nombre in esperados)
    assert any(l.startswith("Sin ubicación") for l in d["traza"])


def test_nivel_bajo_solo_ofrece_el_centro():
    sesion = nueva()
    d = hasta_conclusion(sesion, "tengo congestion nasal y estornudos")
    assert d["urgencia"] == "urgencia_baja" and d["ruta"] is None and not d["fuera_de_zona"]
    assert etiquetas(d) == ["Sí", "No"]


# ---------- respaldo: sin red_lima.json se usa el grafo de distritos ----------
def test_respaldo_ruta_desde_ubicacion(sin_red):
    d = ruta_de_emergencia((-12.08312, -77.03488))
    ruta = d["ruta"]
    assert ruta is not None and len(ruta["puntos"]) == 2 and len(ruta["linea"]) >= 2
    assert ruta["puntos"][0] == {"nombre": "Tu ubicación", "lat": -12.083, "lng": -77.035}
    assert any(l.startswith("Ubicación → vértice u conectado a ") for l in d["traza"])


@pytest.mark.parametrize("punto", [SAN_JUAN_DE_MIRAFLORES, AREQUIPA])
def test_respaldo_fuera_de_zona(sin_red, punto):
    d = ruta_de_emergencia(punto)
    assert d["fuera_de_zona"] and d["ruta"] is None and FUERA in d["mensaje"]


def test_respaldo_si_los_establecimientos_no_tienen_nodo(monkeypatch):
    """Red presente pero grafo.json sin 'nodo' (datos sin actualizar): no hay error, se usa el grafo de distritos."""
    monkeypatch.setattr(red_vial, "cargar_red", lambda: RED)
    sin_nodo = {k: {c: v for c, v in e.items() if c != "nodo"}
                for k, e in ruteo.establecimientos_del_nivel("urgencia_alta").items()}
    monkeypatch.setattr(ruteo, "establecimientos_del_nivel", lambda nivel: sin_nodo)
    plan = ruteo.planificar("urgencia_alta", -12.0605, -77.0395)     # cerca de los nodos de la red de juguete
    assert plan["ruta"] is not None and any(l.startswith("Ubicación → vértice u") for l in plan["traza"])


def test_destino_segun_el_nivel():
    alta = ruteo.planificar("urgencia_alta", *UNMSM)["ruta"]["destino"]
    assert alta in {e["nombre"] for e in ruteo.establecimientos_del_nivel("urgencia_alta").values()}
    media = ruteo.planificar("urgencia_media", *UNMSM, seguro="sis")["ruta"]["destino"]
    assert media in {e["nombre"] for e in ruteo.establecimientos_del_nivel("urgencia_media").values()}
    assert alta != media
