"""Duración e intensidad: temperatura y días del texto libre, y las preguntas de seguimiento del árbol."""
import pytest

from app import datos
from app.main import MAX_TURNOS, sesiones
from app.motor import arbol, dialogo, medidas, preguntas, verificacion
from tests.ayudas import enviar, hasta_conclusion, nueva, tiene_accion, etiquetas


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def hasta_pregunta(sesion, objetivo, grupo="Persona de 5 a 59 años"):
    """Responde 'no' (y la edad) hasta que la pendiente sea `objetivo`. Devuelve la última respuesta."""
    r = None
    for _ in range(30):
        p = sesiones[sesion]["pendiente"]
        if p == objetivo:
            return r
        assert p is not None, f"el triaje terminó sin preguntar {objetivo}"
        r = enviar(sesion, grupo if p == "grupo_edad" else "no")
    raise AssertionError("no llegó")


# ---------- medidas del texto ----------
@pytest.mark.parametrize("texto, grados", [
    ("tengo 39 de fiebre", 39.0), ("38.5 grados", 38.5), ("38,5 grados", 38.5), ("fiebre de 39", 39.0),
    ("temperatura 38,2", 38.2), ("me midieron 40°", 40.0), ("37.2 grados", 37.2),
])
def test_temperatura_del_texto(texto, grados):
    assert medidas.temperatura(texto) == grados


@pytest.mark.parametrize("texto", ["tengo 38 años", "hace 20 grados de calor", "pesa 70 kilos", "tengo tos", "son las 39"])
def test_numeros_que_no_son_temperatura(texto):
    assert medidas.temperatura(texto) is None


def test_desde_38_grados_es_fiebre():
    assert [medidas.es_fiebre(g) for g in (37.9, 38.0, 38.5, 40)] == [False, True, True, True]


@pytest.mark.parametrize("texto, dias", [
    ("fiebre de 5 días", 5), ("hace 4 días", 4), ("4 dias con fiebre", 4), ("desde hace 2 días", 2),
    ("más de 3 días", 4), ("1 día", 1),
])
def test_dias_del_texto(texto, dias):
    assert medidas.dias(texto) == dias


@pytest.mark.parametrize("texto", ["desde el lunes", "hace una semana", "ayer", "tengo fiebre", "hace mucho"])
def test_solo_numeros_de_dias(texto):
    assert medidas.dias(texto) is None


# ---------- fiebre: temperatura y duración ----------
def test_tengo_39_de_fiebre_cuenta_como_fiebre():
    sesion = nueva()
    r = enviar(sesion, "tengo 39 de fiebre")
    assert "fiebre" in sesiones[sesion]["presentes"] and r["estado"] == "TRIAJE"


def test_38_5_grados_sin_la_palabra_fiebre_cuenta_como_fiebre():
    sesion = nueva()
    r = enviar(sesion, "me midieron 38.5 grados")
    assert "fiebre" in sesiones[sesion]["presentes"]
    assert any("Temperatura 38.5 °C ≥ 38 °C: cuenta como fiebre" in l for l in r["traza"])


def test_37_grados_no_es_fiebre_y_queda_en_la_traza():
    sesion = nueva()
    r = enviar(sesion, "me midieron 37.2 grados y me duele la cabeza")
    assert "fiebre" not in sesiones[sesion]["presentes"]
    assert any("menor que 38 °C, no cuenta como fiebre" in l for l in r["traza"])


def test_con_fiebre_se_pregunta_desde_cuando_con_tres_opciones():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = None
    while sesiones[sesion]["pendiente"] != "duracion_fiebre":
        p = sesiones[sesion]["pendiente"]
        r = enviar(sesion, "Persona de 5 a 59 años" if p == "grupo_edad" else "no")
    assert r["mensaje"] == "¿Desde cuándo tienes fiebre?" and etiquetas(r) == ["Hoy", "1 a 3 días", "Más de 3 días"]


def test_la_duracion_se_pregunta_despues_de_la_alarma_y_los_factores():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    orden = []
    while sesiones[sesion]["pendiente"]:
        p = sesiones[sesion]["pendiente"]
        orden.append(p)
        enviar(sesion, "Persona de 5 a 59 años" if p == "grupo_edad" else ("Hoy" if p == "duracion_fiebre" else "no"))
    assert orden.index("duracion_fiebre") > max(orden.index(x) for x in ("dificultad_respirar", "dolor_pecho", "grupo_edad", "embarazo", "enfermedad_cronica"))
    assert orden.count("duracion_fiebre") == 1


def test_mas_de_3_dias_agrega_fiebre_persistente_y_la_regla():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    hasta_pregunta(sesion, "duracion_fiebre")
    r = enviar(sesion, "Más de 3 días")
    assert "fiebre_persistente" in sesiones[sesion]["presentes"]
    assert any("Respuesta a 'duracion_fiebre': «Más de 3 días»" in l for l in r["traza"])
    r = hasta_conclusion_desde(sesion)
    assert any(l.startswith("U9:") for l in r["traza"]) and r["urgencia"] == "urgencia_media"


def hasta_conclusion_desde(sesion):
    from tests.ayudas import confirmar_si_toca
    r = None
    for _ in range(30):
        p = sesiones[sesion]["pendiente"]
        if p is None:
            return confirmar_si_toca(sesion, r)
        r = enviar(sesion, "Persona de 5 a 59 años" if p == "grupo_edad" else ("Hoy" if p == "duracion_fiebre" else "no"))
    raise AssertionError


def test_hoy_y_1_a_3_dias_niegan_fiebre_persistente():
    for etiqueta in ("Hoy", "1 a 3 días"):
        sesion = nueva()
        enviar(sesion, "tengo fiebre")
        hasta_pregunta(sesion, "duracion_fiebre")
        enviar(sesion, etiqueta)
        assert "fiebre_persistente" in sesiones[sesion]["ausentes"] and "fiebre_persistente" not in sesiones[sesion]["presentes"]


def test_fiebre_de_5_dias_activa_la_regla_de_fiebre_persistente_sin_preguntar():
    sesion = nueva()
    r = enviar(sesion, "tengo fiebre de 5 días")
    assert "fiebre_persistente" in sesiones[sesion]["presentes"] and "duracion_fiebre" in sesiones[sesion]["respondidas"]
    assert any("duración detectada en el texto: 5 días" in l for l in r["traza"])
    assert "duracion_fiebre" not in preguntas_que_hace(sesion)
    fin = preguntas_que_hace.ultima
    assert any(l.startswith("U9: fiebre_persistente → urgencia_media") for l in fin["traza"])
    assert fin["urgencia"] == "urgencia_media"


def preguntas_que_hace(sesion):
    """Contesta lo menos alarmante hasta el final. Devuelve las preguntas hechas; la última respuesta queda en .ultima."""
    hechas = []
    ultima = None
    while sesiones[sesion]["pendiente"]:
        p = sesiones[sesion]["pendiente"]
        hechas.append(p)
        ultima = enviar(sesion, "Persona de 5 a 59 años" if p == "grupo_edad" else ("Hoy" if p == "duracion_fiebre" else "no"))
    from tests.ayudas import confirmar_si_toca
    preguntas_que_hace.ultima = confirmar_si_toca(sesion, ultima) if ultima else ultima
    return hechas


@pytest.mark.parametrize("texto, esperado", [("tengo fiebre hace 2 días", False), ("tengo fiebre hace 3 días", False),
                                             ("tengo fiebre hace 4 días", True), ("fiebre de más de 3 días", True)])
def test_el_limite_de_la_fiebre_persistente_es_mas_de_3_dias(texto, esperado):
    sesion = nueva()
    enviar(sesion, texto)
    assert ("fiebre_persistente" in sesiones[sesion]["presentes"]) is esperado


def test_se_puede_contestar_la_duracion_con_un_numero_o_con_palabras():
    for respuesta, persistente in [("hace 4 días", True), ("2 días", False), ("hoy", False), ("ayer", False), ("varios días", True)]:
        sesion = nueva()
        enviar(sesion, "tengo fiebre")
        hasta_pregunta(sesion, "duracion_fiebre")
        enviar(sesion, respuesta)
        assert ("fiebre_persistente" in sesiones[sesion]["presentes"]) is persistente, respuesta


def test_sin_fiebre_no_se_pregunta_la_duracion():
    sesion = nueva()
    enviar(sesion, "tengo tos")
    assert "duracion_fiebre" not in preguntas_que_hace(sesion)
    sesion = nueva()
    enviar(sesion, "no tengo fiebre y tengo tos")
    assert "duracion_fiebre" not in preguntas_que_hace(sesion)


# ---------- dolor abdominal: intensidad ----------
def test_con_dolor_abdominal_se_pregunta_que_tan_fuerte():
    sesion = nueva()
    enviar(sesion, "me duele la barriga")
    r = hasta_pregunta(sesion, "intensidad_dolor_abdominal")
    assert r["mensaje"] == "¿Qué tan fuerte es el dolor de barriga?"
    assert etiquetas(r) == ["Leve", "Moderado", "Fuerte y no se me pasa"]


def test_dolor_de_barriga_fuerte_es_urgencia_alta():
    sesion = nueva()
    enviar(sesion, "me duele la barriga")
    hasta_pregunta(sesion, "intensidad_dolor_abdominal")
    r = enviar(sesion, "Fuerte y no se me pasa")
    assert r["urgencia"] == "urgencia_alta" and tiene_accion(r, "ubicacion")
    assert "dolor_abdominal_intenso" in sesiones[sesion]["presentes"]
    assert any(l.startswith("A6:") for l in r["traza"])                    # la regla de alarma del dolor abdominal intenso


@pytest.mark.parametrize("respuesta", ["Fuerte", "muy fuerte", "insoportable"])
def test_fuerte_escrito_a_mano_tambien_es_alarma(respuesta):
    sesion = nueva()
    enviar(sesion, "me duele la barriga")
    hasta_pregunta(sesion, "intensidad_dolor_abdominal")
    assert enviar(sesion, respuesta)["urgencia"] == "urgencia_alta"


@pytest.mark.parametrize("etiqueta", ["Leve", "Moderado"])
def test_leve_y_moderado_no_son_alarma(etiqueta):
    sesion = nueva()
    enviar(sesion, "me duele la barriga")
    hasta_pregunta(sesion, "intensidad_dolor_abdominal")
    r = enviar(sesion, etiqueta)
    assert r["urgencia"] != "urgencia_alta" and "dolor_abdominal_intenso" not in sesiones[sesion]["presentes"]
    assert "intensidad_dolor_abdominal" in sesiones[sesion]["respondidas"]


def test_la_intensidad_se_pregunta_una_sola_vez():
    sesion = nueva()
    enviar(sesion, "me duele la barriga")
    assert preguntas_que_hace_con_leve(sesion).count("intensidad_dolor_abdominal") == 1


def preguntas_que_hace_con_leve(sesion):
    hechas = []
    while sesiones[sesion]["pendiente"]:
        p = sesiones[sesion]["pendiente"]
        hechas.append(p)
        enviar(sesion, {"grupo_edad": "Persona de 5 a 59 años", "intensidad_dolor_abdominal": "Leve", "duracion_fiebre": "Hoy"}.get(p, "no"))
    return hechas


def test_dolor_de_barriga_fuerte_dicho_de_entrada_es_alarma_directa():
    assert enviar(nueva(), "me duele mucho la barriga")["urgencia"] == "urgencia_alta"


# ---------- el árbol y MAX_TURNOS ----------
def test_los_seguimientos_estan_en_el_arbol_y_cuentan_en_la_altura():
    datos_arbol = datos.cargar("arbol")
    assert {(sg["si"], sg["pregunta"]) for sg in datos_arbol["seguimientos"]} == {
        ("fiebre", "duracion_fiebre"), ("dolor_abdominal", "intensidad_dolor_abdominal")}
    assert {"duracion_fiebre", "intensidad_dolor_abdominal"} <= arbol.preguntados()
    assert arbol.altura_total() == arbol.altura(arbol.raiz()) + 2


def test_max_turnos_cubre_la_altura_total():
    assert MAX_TURNOS > arbol.altura_total()                               # I10: la conversación siempre termina
    assert verificacion.i10_terminacion(MAX_TURNOS, arbol.altura_total()) == []
    assert verificacion.i10_terminacion(arbol.altura_total() - 1, arbol.altura_total())


def test_el_peor_recorrido_cabe_en_max_turnos():
    """Fiebre + diarrea + dolor de barriga recorre muchas preguntas: no debe toparse con el límite antes de terminar."""
    sesion = nueva()
    enviar(sesion, "tengo fiebre y diarrea")
    hechas = preguntas_que_hace_con_leve(sesion)
    assert len(hechas) + 1 <= MAX_TURNOS


def test_los_seguimientos_rotos_se_detectan():
    especiales = datos.preguntas_especiales()
    arbol_roto = {"seguimientos": [{"si": "inventado", "pregunta": "no_existe"}]}
    assert len(verificacion.i3_preguntas_especiales(arbol_roto, {}, {"fiebre"})) == 2
    roto = {"p": {"opciones": [{"id": "a", "efecto": {"presentes": ["fantasma"]}}, {"id": "a", "efecto": {}}]}}
    p = verificacion.i3_preguntas_especiales({}, roto, {"fiebre"})
    assert len(p) == 2 and any("repite el id" in x for x in p) and any("'fantasma'" in x for x in p)
    assert verificacion.i3_preguntas_especiales(datos.cargar("arbol"), especiales, set(datos.sintomas()) | set(datos.factores())) == []


# ---------- reconocer opciones ----------
@pytest.mark.parametrize("texto, id_opcion", [
    ("Más de 3 días", "mas_3_dias"), ("1 a 3 días", "1_3_dias"), ("Hoy", "hoy"), ("hace 5 días", "mas_3_dias"),
    ("3 días", "1_3_dias"), ("una semana", "mas_3_dias"),
])
def test_reconocer_opcion_de_duracion(texto, id_opcion):
    assert preguntas.reconocer_opcion("duracion_fiebre", texto, medidas.dias(texto))["id"] == id_opcion


def test_las_etiquetas_de_los_botones_se_reconocen_a_si_mismas():
    for pid, q in datos.preguntas_especiales().items():
        for texto, op in zip(dialogo.pregunta_y_opciones(pid)[1], q.get("opciones", [])):
            assert preguntas.reconocer_opcion(pid, texto.valor, medidas.dias(texto.valor))["id"] == op["id"]
