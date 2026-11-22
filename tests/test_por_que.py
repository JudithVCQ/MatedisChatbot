"""«¿Por qué me preguntas esto?»: explicación con relaciones.py, sin avanzar la conversación."""
import copy

import pytest

from app import datos
from app.main import sesiones
from app.motor import arbol, dialogo, fsm, relaciones
from tests.ayudas import enviar, etiquetas, nueva, respuesta_a


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def tiene_por_que(r) -> bool:
    return any(o["accion"] == "por_que" and o["etiqueta"] == "¿Por qué?" for o in r["opciones"])


def reglas():
    return datos.cargar("reglas")["reglas"]


def cuadros_con_el_literal_segun_las_reglas(literal: str) -> set[str]:
    """Búsqueda independiente en reglas.json (sirve de oráculo): cuadros que tienen el literal en alguna regla."""
    cuadros = set(datos.cuadros())
    hallados = set()
    for r in reglas():
        premisas = {p.lstrip("~") for p in r["si"]}
        if literal in premisas:
            if r["entonces"] in cuadros:
                hallados.add(r["entonces"])
            hallados |= premisas & cuadros
    return hallados


# ---------- el botón ----------
def test_cada_pregunta_del_triaje_trae_el_boton_por_que():
    sesion = nueva()
    r = enviar(sesion, "tengo fiebre")
    revisadas = 0
    while sesiones[sesion]["pendiente"]:
        assert tiene_por_que(r), sesiones[sesion]["pendiente"]
        assert "¿Por qué?" not in etiquetas(r)                      # no es una respuesta rápida
        revisadas += 1
        r = enviar(sesion, respuesta_a(sesiones[sesion]["pendiente"]))
    assert revisadas >= 8


def test_lo_que_no_es_una_pregunta_no_trae_el_boton():
    assert not tiene_por_que(enviar(nueva(), ""))                                    # saludo
    assert not tiene_por_que(enviar(nueva(), "tengo dolor"))                         # aclaración
    sesion = nueva()
    enviar(sesion, "me duele el pecho")
    assert not tiene_por_que(enviar(sesion, "", ubicacion_denegada=True))


def test_las_preguntas_de_opciones_tambien_lo_traen():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no"); r = enviar(sesion, "no")
    assert sesiones[sesion]["pendiente"] == "grupo_edad" and tiene_por_que(r)


# ---------- no avanza la conversación ----------
def foto(s: dict) -> dict:
    return copy.deepcopy({k: v for k, v in s.items()})


def test_la_explicacion_no_avanza_la_conversacion_ni_consume_turno():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no")
    antes = foto(sesiones[sesion])
    r = enviar(sesion, "¿Por qué?")
    despues = sesiones[sesion]
    assert despues == antes                                         # nada cambió: turnos, pendiente, estado, pila, presentes…
    assert despues["turnos"] == antes["turnos"] and len(despues["pila"]) == len(antes["pila"])
    assert any(l.startswith("Mealy: δ(TRIAJE, explicar) = TRIAJE") and "no consume turno" in l for l in r["traza"])


def test_despues_de_explicar_se_repite_la_misma_pregunta_con_sus_botones():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    pregunta = dialogo.pregunta_y_opciones(sesiones[sesion]["pendiente"])[0]
    r = enviar(sesion, "¿Por qué?")
    assert r["mensaje"].splitlines()[-1] == pregunta and etiquetas(r) == ["Sí", "No"] and tiene_por_que(r)
    r2 = enviar(sesion, "No")                                       # y se puede seguir respondiendo normal
    assert any(l.startswith("Respuesta a 'dificultad_respirar': no") for l in r2["traza"])


def test_se_puede_pedir_la_explicacion_varias_veces_y_es_la_misma():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    a = enviar(sesion, "¿Por qué?")["mensaje"]
    b = enviar(sesion, "¿Por qué?")["mensaje"]
    assert a == b and sesiones[sesion]["turnos"] == 1


def test_por_que_no_agrega_a_la_pila_de_deshacer():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    n = len(sesiones[sesion]["pila"])
    enviar(sesion, "¿Por qué?"); enviar(sesion, "¿Por qué?")
    assert len(sesiones[sesion]["pila"]) == n
    r = enviar(sesion, "Me equivoqué")                              # y deshacer vuelve al saludo, no a una explicación
    assert r["estado"] == "SALUDO"


@pytest.mark.parametrize("texto", ["¿Por qué?", "por que", "¿Por qué me preguntas esto?", "para que", "¿para qué me preguntas eso?"])
def test_formas_de_pedir_la_explicacion(texto):
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = enviar(sesion, texto)
    assert any("Explicación de 'dificultad_respirar'" in l for l in r["traza"])


def test_un_mensaje_con_sintomas_que_empieza_con_por_que_es_un_mensaje_normal():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = enviar(sesion, "por que tengo tos")
    assert "tos" in sesiones[sesion]["presentes"] and not any("Explicación" in l for l in r["traza"])


def test_sin_pregunta_pendiente_por_que_no_rompe():
    r = enviar(nueva(), "¿Por qué?")
    assert r["mensaje"] and not any("Explicación" in l for l in r["traza"])


# ---------- el contenido: solo cuadros que de verdad tienen ese dato en sus reglas ----------
def test_ejemplo_dolor_ojos_con_fiebre_y_dolor_de_cuerpo():
    texto, cuadros = dialogo.explicacion("dolor_ojos", {"fiebre", "dolor_muscular"})
    assert cuadros == ["dengue"]
    assert texto == "Con dolor de cuerpo o músculos y fiebre, esta respuesta ayuda a confirmar o descartar dengue."


def test_ejemplo_tos_con_fiebre_distingue_varios_cuadros():
    texto, cuadros = dialogo.explicacion("tos", {"fiebre"})
    assert set(cuadros) == {"gripe", "covid19", "neumonia", "faringitis"}
    assert "ayuda a distinguir entre" in texto and "dengue" not in texto and "resfrío" not in texto


@pytest.mark.parametrize("presentes", [set(), {"fiebre"}, {"fiebre", "tos"}, {"diarrea"}, {"congestion_nasal", "estornudos"},
                                       {"fiebre", "dolor_muscular", "dolor_ojos"}])
def test_la_explicacion_nombra_solo_cuadros_que_tienen_ese_dato_en_alguna_regla(presentes):
    for pregunta in arbol.preguntados():
        texto, cuadros = dialogo.explicacion(pregunta, presentes)
        permitidos = set()
        for lit in relaciones.literales_de_pregunta(pregunta):
            permitidos |= cuadros_con_el_literal_segun_las_reglas(lit)            # oráculo independiente
        assert set(cuadros) <= permitidos, (pregunta, presentes, cuadros, permitidos)
        for c in datos.cuadros():                                                 # el texto nombra exactamente esos cuadros
            nombre = dialogo.fichas.nombre_en_frase(c)
            assert (nombre in texto) == (c in cuadros), (pregunta, c, texto)


def test_los_cuadros_de_la_explicacion_son_candidatos_actuales_cuando_los_hay():
    presentes = {"fiebre", "dolor_muscular"}
    candidatos = set(relaciones.candidatos(presentes))
    for pregunta in ("tos", "dolor_ojos", "dolor_garganta", "perdida_olfato", "sarpullido"):
        cuadros = set(relaciones.cuadros_de_pregunta(pregunta, presentes))
        con_literal = cuadros_con_el_literal_segun_las_reglas(pregunta)
        assert cuadros <= con_literal
        if con_literal & candidatos:
            assert cuadros <= candidatos                                          # filtra por los candidatos actuales


def test_si_ningun_candidato_lo_tiene_se_nombran_todos_los_que_lo_tienen():
    # con «diarrea» ya dicho, el candidato es gastroenteritis; «dolor_ojos» solo está en dengue (que no es candidato)
    assert relaciones.cuadros_de_pregunta("dolor_ojos", {"diarrea"}) == ["dengue"]


def test_una_pregunta_de_alarma_dice_que_es_de_seguridad():
    texto, _ = dialogo.explicacion("dolor_pecho", {"fiebre"})
    assert texto.startswith("Es una pregunta de seguridad")
    texto, cuadros = dialogo.explicacion("dificultad_respirar", {"fiebre", "tos"})
    assert "seguridad" in texto and cuadros == ["neumonia"] and "neumonía" in texto


def test_los_factores_explican_que_suben_la_urgencia_de_los_cuadros_que_afectan():
    texto, cuadros = dialogo.explicacion("embarazo", {"fiebre", "tos"})
    assert cuadros == ["gripe"] and "También puede subir qué tan urgente es tu caso." in texto
    _, cuadros = dialogo.explicacion("grupo_edad", {"fiebre"})
    assert set(cuadros) <= {"gripe", "dengue", "gastroenteritis"} and cuadros


def test_afecta_la_urgencia_segun_las_reglas():
    assert relaciones.afecta_la_urgencia("embarazo") and relaciones.afecta_la_urgencia("fiebre_persistente")
    assert not relaciones.afecta_la_urgencia("cansancio") and not relaciones.afecta_la_urgencia("perdida_olfato")


def test_literales_de_las_preguntas_especiales():
    assert relaciones.literales_de_pregunta("grupo_edad") == {"menor_6_meses", "menor_5", "mayor_60"}
    assert relaciones.literales_de_pregunta("duracion_fiebre") == {"fiebre_persistente"}
    assert relaciones.literales_de_pregunta("intensidad_dolor_abdominal") == {"dolor_abdominal_intenso"}
    assert relaciones.literales_de_pregunta("tos") == {"tos"}


def test_la_explicacion_no_inventa_nombres_ni_muestra_ids():
    for pregunta in arbol.preguntados():
        texto, _ = dialogo.explicacion(pregunta, {"fiebre", "tos"})
        assert "_" not in texto, (pregunta, texto)


# ---------- Mealy ----------
def test_explicar_esta_en_sigma_y_delta_sigue_total():
    assert "explicar" in fsm.SIGMA and fsm.es_total()
    assert all(fsm.DELTA[(q, "explicar")] == (q, "explicar") for q in fsm.Q)
