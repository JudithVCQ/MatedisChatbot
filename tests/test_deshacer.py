"""Deshacer («Me equivoqué»): pila de estados de la sesión (Mealy extendida con memoria)."""
import pytest

from app.main import MAX_PILA, sesiones
from app.motor import dialogo, fsm
from tests.ayudas import UNMSM, enviar, etiquetas, nueva, respuesta_a, tiene_accion


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def boton_deshacer(r) -> bool:
    return any(o["accion"] == "deshacer" and o["etiqueta"] == "Me equivoqué" for o in r["opciones"])


# ---------- el botón ----------
def test_con_la_pila_vacia_el_boton_no_aparece():
    r = enviar(nueva(), "")                                   # el saludo no es una respuesta del usuario
    assert not boton_deshacer(r) and r["opciones"]


def test_aparece_despues_de_cada_respuesta_del_usuario():
    sesion = nueva()
    r = enviar(sesion, "tengo fiebre")
    assert boton_deshacer(r) and len(sesiones[sesion]["pila"]) == 1
    for esperada in (2, 3, 4):
        r = enviar(sesion, "no")
        assert boton_deshacer(r) and len(sesiones[sesion]["pila"]) == esperada


def test_no_cuenta_como_respuesta_ni_como_opcion_rapida():
    r = enviar(nueva(), "tengo fiebre")
    assert "Me equivoqué" not in etiquetas(r) and etiquetas(r) == ["Sí", "No"]


# ---------- deshacer ----------
def test_responder_si_por_error_deshacer_repite_la_misma_pregunta_y_el_sintoma_desaparece():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")                                      # «¿Te cuesta respirar?» → no
    q = sesiones[sesion]["pendiente"]                         # dolor_pecho
    pregunta = enviar(sesion, "no")                           # (avanza a la edad)
    r = enviar(sesion, "Me equivoqué")                        # deshace «no» a dolor_pecho
    assert sesiones[sesion]["pendiente"] == q and "dolor_pecho" not in sesiones[sesion]["ausentes"]
    assert "Sin problema, volvamos atrás." in r["mensaje"]
    assert r["mensaje"].endswith("¿Sientes dolor u opresión en el pecho?")
    assert etiquetas(r) == ["Sí", "No"]


def test_un_si_por_error_se_deshace_y_el_sintoma_no_queda():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")                                      # dificultad_respirar: no
    r = enviar(sesion, "sí")                                  # dolor_pecho: sí (por error) → alarma
    assert r["urgencia"] == "urgencia_alta" and "dolor_pecho" in sesiones[sesion]["presentes"]
    r = enviar(sesion, "Me equivoqué")
    assert "dolor_pecho" not in sesiones[sesion]["presentes"] and sesiones[sesion]["pendiente"] == "dolor_pecho"
    assert r["mensaje"].splitlines()[-1] == "¿Sientes dolor u opresión en el pecho?"
    assert r["estado"] == "TRIAJE" and r["urgencia"] is None


def test_deshacer_una_alarma_restaura_pero_avisa():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    enviar(sesion, "sí")                                      # dolor de pecho → alarma
    r = enviar(sesion, "Me equivoqué")
    assert "Si de verdad tienes ese síntoma, acude a emergencias o llama al SAMU 106." in r["mensaje"]
    assert any("Se deshizo una respuesta que había dado alarma" in l for l in r["traza"])
    assert r["urgencia"] is None and sesiones[sesion]["estado"] == "TRIAJE"             # se restaura igual


def test_deshacer_algo_que_no_fue_alarma_no_lleva_el_aviso_de_emergencia():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    r = enviar(sesion, "Me equivoqué")
    assert "SAMU" not in r["mensaje"]


def test_deshacer_varias_veces_seguidas_vuelve_paso_a_paso():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    historia = []
    for _ in range(3):
        historia.append(sesiones[sesion]["pendiente"])
        enviar(sesion, "no")
    assert len(sesiones[sesion]["pila"]) == 4
    esperadas = list(reversed(historia))
    for pregunta in esperadas:                                # deshace de la última a la primera
        r = enviar(sesion, "Me equivoqué")
        assert sesiones[sesion]["pendiente"] == pregunta and r["mensaje"].endswith(dialogo.pregunta_y_opciones(pregunta)[0])
    assert len(sesiones[sesion]["pila"]) == 1
    r = enviar(sesion, "Me equivoqué")                        # el primer mensaje: vuelve al saludo
    assert r["estado"] == "SALUDO" and sesiones[sesion]["presentes"] == set() and not boton_deshacer(r)


def test_pila_vacia_deshacer_no_hace_nada_y_lo_dice():
    sesion = nueva()
    r = enviar(sesion, "Me equivoqué")
    assert r["mensaje"] == "No hay nada que deshacer." and not boton_deshacer(r)
    assert any("pila vacía" in l for l in r["traza"])


def test_despues_de_deshacer_se_puede_responder_otra_cosa():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    enviar(sesion, "sí")                                      # alarma por error
    enviar(sesion, "Me equivoqué")
    r = enviar(sesion, "no")                                  # ahora la respuesta correcta
    assert r["urgencia"] is None and "dolor_pecho" in sesiones[sesion]["ausentes"] and sesiones[sesion]["pendiente"] == "grupo_edad"


def test_deshacer_tambien_funciona_escrito_a_mano():
    for texto in ["me equivoqué", "Me equivoque", "deshacer", "volver atrás"]:
        sesion = nueva()
        enviar(sesion, "tengo fiebre")
        enviar(sesion, "no")
        r = enviar(sesion, texto)
        assert sesiones[sesion]["pendiente"] == "dificultad_respirar" and "Sin problema" in r["mensaje"], texto


def test_las_correcciones_de_texto_no_se_confunden_con_deshacer():
    assert not dialogo.es_deshacer("tengo fiebre") and not dialogo.es_deshacer("me duele atrás de la cabeza")
    assert dialogo.es_deshacer("Me equivoqué")


# ---------- otros estados ----------
def test_deshacer_en_el_seguro_repite_la_pregunta_del_seguro_y_olvida_el_seguro_dado():
    sesion = nueva()
    from tests.ayudas import media
    media(sesion)                                             # queda esperando el seguro
    enviar(sesion, "SIS")
    assert sesiones[sesion]["seguro"] == "sis" and sesiones[sesion]["estado"] == "UBICACION"
    r = enviar(sesion, "Me equivoqué")
    assert sesiones[sesion]["seguro"] is None and r["estado"] == "SEGURO" and etiquetas(r)[0] == "SIS"
    assert r["mensaje"].endswith("¿qué seguro tienes?")
    r = enviar(sesion, "EsSalud")                             # y puede elegir otro
    assert sesiones[sesion]["seguro"] == "essalud" and r["estado"] == "UBICACION"


def test_deshacer_en_la_ubicacion_vuelve_a_pedirla():
    sesion = nueva()
    enviar(sesion, "me duele el pecho")
    r = enviar(sesion, "", ubicacion_denegada=True)
    assert r["ruta"] is None
    r = enviar(sesion, "Me equivoqué")
    assert r["estado"] == "UBICACION" and tiene_accion(r, "ubicacion") and etiquetas(r) == ["Compartir mi ubicación", "Prefiero no compartirla"]


def test_deshacer_en_la_confirmacion_vuelve_a_la_ultima_pregunta():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    ultima = None
    while sesiones[sesion]["pendiente"]:
        ultima = sesiones[sesion]["pendiente"]
        enviar(sesion, respuesta_a(ultima, ("dolor_ojos", "dolor_muscular")))
    assert sesiones[sesion]["confirmando"]
    r = enviar(sesion, "Me equivoqué")
    assert not sesiones[sesion]["confirmando"] and sesiones[sesion]["pendiente"] == ultima
    assert r["mensaje"].endswith(dialogo.pregunta_y_opciones(ultima)[0])


def test_deshacer_la_confirmacion_de_corregir_vuelve_a_la_lista_de_quitar():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    while sesiones[sesion]["pendiente"]:
        enviar(sesion, respuesta_a(sesiones[sesion]["pendiente"], ("dolor_ojos",)))
    enviar(sesion, "Corregir")
    enviar(sesion, "Quitar fiebre")
    r = enviar(sesion, "Me equivoqué")
    assert sesiones[sesion]["correccion_modo"] == "elegir" and r["mensaje"].endswith("¿Qué quieres corregir?")
    assert "fiebre" in sesiones[sesion]["presentes"]


# ---------- la pila ----------
def test_la_pila_tiene_un_maximo_de_20():
    assert MAX_PILA == 20
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    for _ in range(30):                                       # 30 respuestas inválidas: cada una apila
        enviar(sesion, "mmm")
    assert len(sesiones[sesion]["pila"]) == MAX_PILA


def test_se_puede_deshacer_hasta_20_pasos_y_ni_uno_mas():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    for _ in range(25):
        enviar(sesion, "mmm")
    for _ in range(MAX_PILA):
        r = enviar(sesion, "Me equivoqué")
    assert len(sesiones[sesion]["pila"]) == 0 and not boton_deshacer(r)
    assert enviar(sesion, "Me equivoqué")["mensaje"] == "No hay nada que deshacer."


def test_la_pila_guarda_copias_independientes():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    primera = sesiones[sesion]["pila"][0]
    antes = (set(primera["presentes"]), set(primera["ausentes"]))
    enviar(sesion, "no"); enviar(sesion, "no")
    assert (primera["presentes"], primera["ausentes"]) == antes                     # lo ya apilado no cambia al seguir
    assert all("pila" not in estado for estado in sesiones[sesion]["pila"])           # la pila no se anida


def test_la_pila_nunca_guarda_coordenadas():
    sesion = nueva()
    enviar(sesion, "me duele el pecho")
    enviar(sesion, "", punto=(-12.08312, -77.03488))
    memoria = repr(sesiones[sesion])
    assert not any(c in memoria for c in ("12.083", "77.035", "12.08312", "77.03488"))


def test_nueva_consulta_con_sintomas_empieza_con_la_pila_limpia():
    from tests.ayudas import media
    sesion = nueva()
    media(sesion)
    enviar(sesion, "tengo tos")                               # consulta nueva: la sesión se reinicia
    assert len(sesiones[sesion]["pila"]) == 1                 # solo el estado de partida de la consulta nueva


# ---------- Mealy ----------
def test_deshacer_esta_en_sigma_y_delta_sigue_total():
    assert "deshacer" in fsm.SIGMA and fsm.es_total()
    assert all((q, "deshacer") in fsm.DELTA and fsm.DELTA[(q, "deshacer")] == (q, "deshacer") for q in fsm.Q)


def test_el_restaurado_queda_en_la_traza():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    r = enviar(sesion, "Me equivoqué")
    assert any(l.startswith("Mealy: δ(TRIAJE, deshacer) = TRIAJE") for l in r["traza"])
    assert any(l.startswith("Mealy+pila: se restaura el estado TRIAJE") for l in r["traza"])
