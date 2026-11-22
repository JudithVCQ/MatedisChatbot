"""Conversación: triaje → seguro → ubicación → ruta. Máquina de Mealy, seguros, relaciones y contrato (opciones/resultado)."""
import pytest

from app import datos
from app.main import sesiones
from app.motor import fsm, relaciones, seguros
from tests.ayudas import (AREQUIPA, NO_RUTA, UNMSM, baja, cliente, emergencia, enviar, etiquetas, hasta_conclusion, media,
                          nueva, rapidas, tiene_accion)

LEY = "Ley 27604"
# Σ completo, en orden. Crece fase a fase: incompleto (1), confirmar y corregir (4), deshacer (5), explicar (6).
SIMBOLOS_ESPERADOS = ["vacio", "invalido", "sintomas", "respuesta", "alarma", "conclusion", "buscar_centro", "seguro",
                      "ubicacion", "incompleto", "confirmar", "corregir", "deshacer", "explicar"]


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def institucion_de(nombre: str) -> str:
    return next(e["institucion"] for e in datos.cargar("grafo")["establecimientos"].values() if e["nombre"] == nombre)


def lineas_mealy(r) -> list[str]:
    return [l for l in r["traza"] if l.startswith("Mealy:")]


# ---------- máquina de Mealy ----------
def test_delta_total_con_los_estados_nuevos():
    assert fsm.Q == ["SALUDO", "TRIAJE", "SEGURO", "UBICACION", "DERIVACION", "ERROR"]
    assert fsm.SIGMA == SIMBOLOS_ESPERADOS
    assert len(fsm.DELTA) == len(fsm.Q) * len(fsm.SIGMA) and fsm.es_total()
    assert all(sig in fsm.Q for sig, _ in fsm.DELTA.values())                 # δ solo lleva a estados que existen


def test_todos_los_estados_son_alcanzables_desde_el_inicio():
    alcanzados, pendientes = {fsm.Q0}, [fsm.Q0]
    while pendientes:
        q = pendientes.pop()
        for s in fsm.SIGMA:
            siguiente, _ = fsm.paso(q, s)
            if siguiente not in alcanzados:
                alcanzados.add(siguiente)
                pendientes.append(siguiente)
    assert alcanzados == set(fsm.Q)


def test_toda_salida_de_mealy_tiene_manejo_en_el_servidor():
    """Cada λ que puede emitir δ debe estar atendida en procesar(): ninguna entrada deja al sistema sin respuesta."""
    atendidas = {"reiniciar", "saludar", "ayuda", "emergencia", "pedir_seguro", "repetir_seguro", "pedir_ubicacion",
                 "repetir_ubicacion", "mostrar_ruta", "cerrar", "repetir", "preguntar", "derivar", "aclarar", "concluir", "corregir", "deshacer", "explicar"}
    assert {salida for _, salida in fsm.DELTA.values()} <= atendidas


# ---------- urgencia ALTA: sin seguro, ubicación de inmediato (Ley 27604) ----------
def test_urgencia_alta_no_pregunta_el_seguro_y_pide_la_ubicacion():
    sesion = nueva()
    r = emergencia(sesion)
    assert r["urgencia"] == "urgencia_alta" and r["estado"] == "UBICACION"
    assert "Comparte tu ubicación para indicarte la emergencia más cercana" in r["mensaje"]
    assert LEY in r["mensaje"] and "sin importar tu seguro" in r["mensaje"]
    assert etiquetas(r) == ["Compartir mi ubicación", "Prefiero no compartirla"]      # ni un solo botón de seguro
    assert sesiones[sesion]["seguro"] is None
    assert any(l.startswith("Mealy: δ(DERIVACION, seguro) = UBICACION") and "Ley 27604" in l for l in lineas_mealy(r))


def test_urgencia_alta_destino_es_la_emergencia_mas_cercana_de_cualquier_institucion():
    sesion = nueva()
    emergencia(sesion)
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and LEY in r["mensaje"] and r["resultado"]["urgencia"] == "urgencia_alta"
    assert any("no se filtra por seguro" in l for l in r["traza"])
    assert any(l.startswith("Mealy: δ(UBICACION, ubicacion) = DERIVACION") for l in lineas_mealy(r))


def test_emergencia_ignora_el_seguro_aunque_ya_se_conozca():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "EPS o seguro privado")          # no hay clínicas privadas: para media sería el respaldo
    enviar(sesion, "", ubicacion_denegada=True)
    emergencia(sesion)
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and not r["resultado"]["nota_seguro"] and "No encontré" not in r["mensaje"]


# ---------- urgencia MEDIA: seguro → ubicación → ruta ----------
def test_urgencia_media_pregunta_el_seguro_con_botones():
    r = media(nueva())
    assert r["urgencia"] == "urgencia_media" and r["estado"] == "SEGURO"
    assert "¿qué seguro tienes?" in r["mensaje"] and "Para indicarte el centro de salud más cercano" in r["mensaje"]
    assert etiquetas(r) == ["SIS", "EsSalud", "EPS o seguro privado", "Sanidad FFAA/PNP", "No tengo seguro", "No sé"]
    assert any(l.startswith("Mealy: δ(DERIVACION, buscar_centro) = SEGURO") for l in lineas_mealy(r))


def test_media_sis_y_ubicacion_en_la_zona_da_destino_minsa_con_ruta():
    sesion = nueva()
    media(sesion)
    r = enviar(sesion, "SIS")
    assert r["estado"] == "UBICACION" and tiene_accion(r, "ubicacion")
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and r["estado"] == "DERIVACION"
    assert institucion_de(r["ruta"]["destino"]) in ("MINSA", "GORE", "Municipal")
    assert r["resultado"]["establecimiento"]["nombre"] == r["ruta"]["destino"]
    assert any(l.startswith("Seguro sis → instituciones") and "∩ nivel" in l for l in r["traza"])   # composición en la traza


def test_media_essalud_da_destino_essalud():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "tengo essalud")
    r = enviar(sesion, "", punto=UNMSM)
    assert institucion_de(r["ruta"]["destino"]) == "EsSalud"


def test_interseccion_vacia_usa_el_respaldo_minsa_y_lo_explica():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "tengo pacifico")                 # EPS privado: no hay clínicas privadas en la zona
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and institucion_de(r["ruta"]["destino"]) in ("MINSA", "GORE")
    assert "No encontré establecimientos de EPS o seguro privado" in r["mensaje"] and "MINSA/GORE" in r["mensaje"]
    assert any("Intersección vacía" in l and "MINSA" in l for l in r["traza"])
    assert r["resultado"]["nota_seguro"] == "Confirma con tu aseguradora qué clínicas cubre tu plan."


def test_sin_seguro_lleva_la_nota_del_sis():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "No tengo seguro")
    r = enviar(sesion, "", punto=UNMSM)
    assert "afiliarte al SIS" in r["resultado"]["nota_seguro"] and institucion_de(r["ruta"]["destino"]) in ("MINSA", "GORE")


# ---------- urgencia BAJA: ofrecer, y solo si acepta ----------
def test_baja_ofrece_un_centro_con_si_no():
    r = baja(nueva())
    assert r["urgencia"] == "urgencia_baja" and r["estado"] == "DERIVACION" and r["ruta"] is None
    assert "¿Quieres que te indique un centro de salud cercano por si lo necesitas?" in r["mensaje"]
    assert etiquetas(r) == ["Sí", "No"]


def test_baja_no_termina_sin_ruta_ni_preguntar_el_seguro():
    sesion = nueva()
    baja(sesion)
    r = enviar(sesion, "No")
    assert r["ruta"] is None and r["estado"] == "DERIVACION" and "seguro" not in r["mensaje"].lower()
    assert sesiones[sesion]["seguro"] is None and rapidas(r) == []


def test_baja_si_lleva_a_seguro_ubicacion_y_ruta():
    sesion = nueva()
    baja(sesion)
    assert etiquetas(enviar(sesion, "Sí"))[0] == "SIS"                    # pregunta el seguro
    assert enviar(sesion, "SIS")["estado"] == "UBICACION"                  # pide la ubicación
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and r["urgencia"] == "urgencia_baja"


# ---------- pedir un centro en cualquier momento ----------
@pytest.mark.parametrize("texto", ["¿Dónde me atiendo?", "hospital cerca", "centro de salud cercano", "una posta por aquí",
                                   "¿Dónde hay un hospital cerca?"])
def test_pedir_un_centro_sin_triaje_usa_el_nivel_de_centro_de_salud(texto):
    sesion = nueva()
    r = enviar(sesion, texto)
    assert r["estado"] == "SEGURO" and etiquetas(r)[0] == "SIS"
    assert any("nivel urgencia_media (aún no hay triaje" in l for l in r["traza"])
    enviar(sesion, "SIS")
    assert enviar(sesion, "", punto=UNMSM)["ruta"] is not None


def test_pedir_un_centro_en_mitad_del_triaje_y_volver_al_triaje():
    sesion = nueva()
    primera = enviar(sesion, "tengo fiebre")
    pregunta = primera["mensaje"]
    r = enviar(sesion, "¿Dónde hay un hospital cerca?")
    assert r["estado"] == "SEGURO" and sesiones[sesion]["retorno"] is True
    assert any("Interrupción del triaje" in l for l in r["traza"])
    assert enviar(sesion, "SIS")["estado"] == "UBICACION"
    r = enviar(sesion, "", punto=UNMSM)
    assert r["ruta"] is not None and r["estado"] == "TRIAJE"                    # vuelve al triaje
    assert "Volvamos al triaje: " + pregunta in r["mensaje"] and etiquetas(r) == ["Sí", "No"]
    assert any("se restaura el estado TRIAJE" in l for l in r["traza"])
    siguiente = enviar(sesion, "no")                                             # y el triaje continúa
    assert siguiente["estado"] == "TRIAJE" and siguiente["mensaje"] != pregunta


def test_sintomas_durante_el_seguro_en_mitad_del_triaje_siguen_el_triaje():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "hospital cerca")
    r = enviar(sesion, "tengo tos")
    assert r["estado"] == "TRIAJE" and any("se cancela la consulta del centro" in l for l in r["traza"])
    assert sesiones[sesion]["centro"] is None and sesiones[sesion]["retorno"] is False


def test_sintomas_durante_el_seguro_tras_una_conclusion_son_una_consulta_nueva():
    sesion = nueva()
    media(sesion)                                  # queda esperando el seguro
    r = enviar(sesion, "tengo tos")
    assert r["estado"] == "TRIAJE" and r["traza"][0] == "Nueva consulta"


def test_alarma_durante_el_seguro_va_a_emergencias():
    sesion = nueva()
    media(sesion)
    r = enviar(sesion, "me falta el aire")
    assert r["urgencia"] == "urgencia_alta" and r["estado"] == "UBICACION"


# ---------- el seguro se pregunta una sola vez por sesión ----------
def test_el_seguro_se_pregunta_una_sola_vez_por_sesion():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "EsSalud")
    enviar(sesion, "", punto=UNMSM)
    r = hasta_conclusion(sesion, "tengo fiebre", {"dolor_ojos", "dolor_muscular"})   # segunda consulta, misma sesión
    assert r["urgencia"] == "urgencia_media" and r["estado"] == "UBICACION"           # directo a la ubicación
    assert etiquetas(r)[0] == "Compartir mi ubicación" and "qué seguro" not in r["mensaje"]
    assert any("seguro ya conocido: essalud" in l for l in r["traza"])
    assert institucion_de(enviar(sesion, "", punto=UNMSM)["ruta"]["destino"]) == "EsSalud"   # y lo reutiliza


def test_pedir_un_centro_con_el_seguro_conocido_salta_la_pregunta():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "SIS")
    enviar(sesion, "", ubicacion_denegada=True)
    r = enviar(sesion, "¿dónde me atiendo?")
    assert r["estado"] == "UBICACION" and tiene_accion(r, "ubicacion") and "qué seguro" not in r["mensaje"]


# ---------- reconocimiento libre del seguro ----------
@pytest.mark.parametrize("texto, esperado", [
    ("tengo sis", "sis"), ("SIS", "sis"), ("el seguro integral", "sis"),
    ("asegurado de essalud", "essalud"), ("EsSalud", "essalud"), ("seguro social", "essalud"),
    ("pacifico", "eps_privado"), ("tengo rimac", "eps_privado"), ("mapfre", "eps_privado"), ("EPS o seguro privado", "eps_privado"),
    ("sanidad de la policia", "ffaa_pnp"), ("Sanidad FFAA/PNP", "ffaa_pnp"),
    ("No tengo seguro", "sin_seguro"), ("no", "sin_seguro"), ("ninguno", "sin_seguro"),
    ("No sé", "no_se"), ("ni idea", "no_se"), ("no se cual tengo", "no_se"),
])
def test_reconoce_el_seguro_en_texto_libre(texto, esperado):
    assert seguros.reconocer(texto) == esperado


def test_cada_boton_de_seguro_se_reconoce_a_si_mismo():
    ids = list(datos.seguros())
    for sid, op in zip(ids, seguros.opciones()):
        assert seguros.reconocer(op["valor"]) == sid, op


@pytest.mark.parametrize("texto", ["blablá", "qué", "lo que sea", "mmm"])
def test_dos_respuestas_no_reconocidas_se_toman_como_no_se(texto):
    sesion = nueva()
    media(sesion)
    r1 = enviar(sesion, texto)
    assert r1["estado"] == "SEGURO" and "no te entendí" in r1["mensaje"] and etiquetas(r1)[0] == "SIS"
    r2 = enviar(sesion, texto)
    assert r2["estado"] == "UBICACION" and sesiones[sesion]["seguro"] == "no_se"
    assert any("dos veces" in l for l in r2["traza"])


# ---------- ubicación: no se pide al cargar, no se guarda, y nunca da error ----------
def test_no_se_pide_la_ubicacion_al_empezar():
    r = enviar(nueva(), "")
    assert r["estado"] == "SALUDO" and not tiene_accion(r, "ubicacion")


def test_una_ubicacion_que_nadie_pidio_se_ignora():
    sesion = nueva()
    r = enviar(sesion, "tengo fiebre", punto=UNMSM)
    assert r["ruta"] is None and any("sin haberla pedido" in l for l in r["traza"])
    assert "-12.056" not in repr(sesiones[sesion]) and "-77.084" not in repr(sesiones[sesion])


@pytest.mark.parametrize("punto", [AREQUIPA, (-12.40, -76.90)])
def test_fuera_de_la_zona_recomienda_sin_ruta_y_ofrece_reintentar(punto):
    sesion = nueva()
    media(sesion)
    enviar(sesion, "SIS")
    r = enviar(sesion, "", punto=punto)
    assert r["ruta"] is None and r["fuera_de_zona"] and "Estás fuera de la zona cubierta. " + NO_RUTA in r["mensaje"]
    assert r["establecimientos"] and etiquetas(r) == ["Intentar de nuevo"] and r["estado"] == "DERIVACION"


def test_negar_la_ubicacion_recomienda_sin_ruta_y_el_reintento_funciona():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "SIS")
    r = enviar(sesion, "", ubicacion_denegada=True)
    assert r["ruta"] is None and not r["fuera_de_zona"] and NO_RUTA in r["mensaje"] and r["establecimientos"]
    assert all(e["nombre"] in r["mensaje"] for e in r["establecimientos"])
    r = enviar(sesion, "", punto=UNMSM)                   # "Intentar de nuevo"
    assert r["ruta"] is not None and rapidas(r) == []


def test_prefiero_no_compartirla_en_la_emergencia():
    sesion = nueva()
    emergencia(sesion)
    r = enviar(sesion, "", ubicacion_denegada=True)
    assert r["ruta"] is None and NO_RUTA in r["mensaje"] and LEY in r["mensaje"]


def test_texto_libre_mientras_se_espera_la_ubicacion_la_vuelve_a_pedir():
    sesion = nueva()
    emergencia(sesion)
    r = enviar(sesion, "asdfgh")
    assert r["estado"] == "UBICACION" and "Necesito tu ubicación" in r["mensaje"] and tiene_accion(r, "ubicacion")


def test_el_selector_de_distrito_ya_no_existe():
    assert cliente.get("/api/distritos").status_code == 404
    sesion = nueva()
    emergencia(sesion)
    r = cliente.post("/api/chat", json={"sesion": sesion, "mensaje": "", "distrito": "lince"}).json()
    assert r["ruta"] is None                    # un 'distrito' enviado por un cliente viejo se ignora: no hay origen


# ---------- contrato: opciones y resultado ----------
def test_las_preguntas_del_triaje_traen_si_no():
    r = enviar(nueva(), "tengo fiebre")
    assert r["estado"] == "TRIAJE" and [(o["etiqueta"], o["valor"], o["accion"]) for o in rapidas(r)] == \
        [("Sí", "sí", "enviar"), ("No", "no", "enviar")]


def test_el_boton_si_no_se_entiende_como_respuesta():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = enviar(sesion, "sí")                              # lo que envía el botón «Sí»
    assert any(l.startswith("Respuesta a ") and l.endswith(": sí") for l in r["traza"])


def test_resultado_estructurado_tras_la_conclusion():
    r = media(nueva())
    res = r["resultado"]
    assert (res["cuadro"], res["cie10"], res["urgencia"]) == ("Dengue", "A97.0", "urgencia_media")
    assert res["cuidados"] and res["volver_si"] and res["establecimiento"] is None and res["nota_seguro"] is None


def test_resultado_con_el_establecimiento_tras_la_ruta():
    sesion = nueva()
    media(sesion)
    enviar(sesion, "SIS")
    res = enviar(sesion, "", punto=UNMSM)["resultado"]
    est = res["establecimiento"]
    assert set(est) == {"nombre", "direccion", "telefono", "minutos"} and est["minutos"] >= 1
    assert res["urgencia"] == "urgencia_media" and res["cuadro"] is None          # la tarjeta del cuadro ya se mostró antes


def test_la_emergencia_sin_cuadro_trae_resultado_de_urgencia_alta():
    r = emergencia(nueva())
    assert r["resultado"]["urgencia"] == "urgencia_alta" and r["resultado"]["cuadro"] is None
    assert r["resultado"]["cuidados"] == [] and r["resultado"]["establecimiento"] is None


def test_respuestas_sin_resultado_ni_opciones_cuando_no_corresponde():
    r = enviar(nueva(), "")
    assert r["resultado"] is None and [o["etiqueta"] for o in r["opciones"]] == [
        "Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Dolor de cabeza", "Otro síntoma"]     # el saludo trae atajos


# ---------- relaciones: seguro → institución → establecimiento ----------
def test_composicion_seguro_institucion_establecimiento():
    ids_seguros, instituciones, establecimientos, m_si, m_ie, m_se = relaciones.matrices_seguro()
    assert (len(m_si), len(m_si[0])) == (len(ids_seguros), len(instituciones))
    assert (len(m_ie), len(m_ie[0])) == (len(instituciones), len(establecimientos))
    assert m_se == relaciones.producto_booleano(m_si, m_ie)
    grafo = datos.cargar("grafo")["establecimientos"]
    for i, sid in enumerate(ids_seguros):                       # M_SE[s][e] = 1  ⇔  la institución de e la acepta el seguro s
        for j, eid in enumerate(establecimientos):
            assert m_se[i][j] == int(grafo[eid]["institucion"] in datos.seguros()[sid]["instituciones"])
    assert all(sum(f) == 1 for f in zip(*m_ie))                 # cada establecimiento pertenece a exactamente una institución


def test_destinos_por_seguro_interseca_con_el_nivel():
    aceptables = {"cs_ejemplo_lince", "cs_ejemplo_essalud", "cs_ejemplo_rimac"}
    ids, linea = relaciones.destinos_por_seguro("essalud", aceptables)
    assert ids == ["cs_ejemplo_essalud"] and linea.startswith("Seguro essalud → instituciones ['EsSalud']")
    assert relaciones.destinos_por_seguro("sis", aceptables)[0] == ["cs_ejemplo_lince", "cs_ejemplo_rimac"]
    assert relaciones.destinos_por_seguro("eps_privado", aceptables)[0] == []
    assert relaciones.cubiertos_por_instituciones(["EsSalud"]) == ["h_rebagliati", "cs_ejemplo_essalud"]


def test_datos_de_seguros():
    cfg = datos.cargar("seguros")
    assert list(datos.seguros()) == ["sis", "essalud", "eps_privado", "ffaa_pnp", "sin_seguro", "no_se"]
    assert datos.seguros()["sis"]["instituciones"] == ["MINSA", "GORE", "Municipal"]
    assert datos.seguros()["essalud"]["instituciones"] == ["EsSalud"]
    assert datos.seguros()["eps_privado"]["instituciones"] == ["Privado"]
    assert datos.seguros()["ffaa_pnp"]["instituciones"] == ["FFAA", "PNP"]
    assert datos.seguros()["sin_seguro"]["instituciones"] == datos.seguros()["no_se"]["instituciones"] == ["MINSA", "GORE"]
    assert cfg["respaldo_instituciones"] == ["MINSA", "GORE"]
    assert all(e["institucion"] and e["revisar"] for e in datos.cargar("grafo")["establecimientos"].values())
