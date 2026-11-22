"""Preguntas coherentes: grupo de edad (partición), mensajes incompletos, atajos y ayuda."""
import pytest

from app import datos
from app.main import sesiones
from app.motor import dialogo, edad, extractor_keywords as kw, verificacion
from tests.ayudas import enviar, hasta_conclusion, nueva, rapidas, respuesta_a, tiene_accion, etiquetas

SIN_SI_NO = "(sí / no)"


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def preguntas_hasta_el_final(sesion, respuesta_grupo="Persona de 5 a 59 años", si=()):
    """Responde 'no' a todo y devuelve, en orden, las preguntas que hizo el árbol."""
    hechas = []
    for _ in range(40):
        pendiente = sesiones[sesion]["pendiente"]
        if pendiente is None:
            return hechas
        hechas.append(pendiente)
        enviar(sesion, respuesta_a(pendiente, si, respuesta_grupo))
    raise AssertionError("no terminó")


# ---------- grupo de edad: UNA pregunta con 4 opciones excluyentes ----------
def test_la_edad_es_una_sola_pregunta_con_cuatro_opciones():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    enviar(sesion, "no"); r = enviar(sesion, "no")                       # alarmas
    assert sesiones[sesion]["pendiente"] == "grupo_edad"
    assert r["mensaje"] == "¿Para quién es la consulta?"
    assert etiquetas(r) == ["Bebé (menos de 6 meses)", "Niño o niña (menor de 5 años)", "Persona de 5 a 59 años", "Persona de 60 años o más"]
    assert list(datos.grupos_edad()) == ["bebe_menor_6m", "nino_menor_5", "persona_5_59", "persona_60_mas"]
    arbol_json = datos.cargar("arbol")
    assert "menor_6_meses" not in arbol_json["factores"] and "mayor_60" not in arbol_json["factores"]


@pytest.mark.parametrize("etiqueta, gid, literales, ausentes_edad", [
    ("Bebé (menos de 6 meses)", "bebe_menor_6m", {"menor_6_meses", "menor_5"}, {"mayor_60"}),
    ("Niño o niña (menor de 5 años)", "nino_menor_5", {"menor_5"}, {"menor_6_meses", "mayor_60"}),
    ("Persona de 5 a 59 años", "persona_5_59", set(), {"menor_6_meses", "menor_5", "mayor_60"}),
    ("Persona de 60 años o más", "persona_60_mas", {"mayor_60"}, {"menor_6_meses", "menor_5"}),
])
def test_el_grupo_se_guarda_y_genera_los_literales_de_las_reglas(etiqueta, gid, literales, ausentes_edad):
    sesion = nueva()
    enviar(sesion, "tengo fiebre"); enviar(sesion, "no"); enviar(sesion, "no")
    r = enviar(sesion, etiqueta)
    s = sesiones[sesion]
    assert s["grupo"] == gid and literales <= s["presentes"] and ausentes_edad <= s["ausentes"]
    assert not (literales & s["ausentes"]) and "grupo_edad" in s["respondidas"]
    assert any(l.startswith(f"Grupo de edad: {gid}") and "opción elegida" in l for l in r["traza"])      # queda en la traza


def test_nino_menor_de_5_nunca_pregunta_por_60_ni_por_embarazo():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    hechas = preguntas_hasta_el_final(sesion, "Niño o niña (menor de 5 años)")
    assert "embarazo" not in hechas and "mayor_60" not in hechas and "menor_6_meses" not in hechas
    assert "enfermedad_cronica" in hechas                                 # a un niño sí se le pregunta
    assert hechas.count("grupo_edad") == 1


def test_bebe_no_recibe_embarazo_ni_enfermedad_cronica():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    hechas = preguntas_hasta_el_final(sesion, "Bebé (menos de 6 meses)")
    assert "embarazo" not in hechas and "enfermedad_cronica" not in hechas
    assert {"embarazo", "enfermedad_cronica"} <= sesiones[sesion]["no_aplica"]


def test_embarazo_solo_se_pregunta_a_personas_de_5_a_59():
    for etiqueta, pregunta_embarazo in [("Persona de 5 a 59 años", True), ("Persona de 60 años o más", False),
                                        ("Niño o niña (menor de 5 años)", False), ("Bebé (menos de 6 meses)", False)]:
        sesion = nueva()
        enviar(sesion, "tengo fiebre")
        assert ("embarazo" in preguntas_hasta_el_final(sesion, etiqueta)) is pregunta_embarazo, etiqueta


def test_el_no_aplica_queda_en_la_traza():
    r = enviar(nueva(), "mi hijo de 3 años tiene fiebre")
    assert any("no se preguntará: ['embarazo']" in l for l in r["traza"])


# ---------- la edad que ya viene en el texto no se vuelve a preguntar ----------
@pytest.mark.parametrize("texto, gid", [
    ("mi hijo de 3 años tiene fiebre", "nino_menor_5"), ("tengo 70 años y fiebre", "persona_60_mas"),
    ("mi bebe tiene 5 meses y fiebre", "bebe_menor_6m"), ("mi nieto de 8 meses tiene fiebre", "nino_menor_5"),
    ("tengo 12 años y fiebre", "persona_5_59"), ("soy un adulto mayor con fiebre", "persona_60_mas"),
    ("mi bebe tiene fiebre", "nino_menor_5"),
])
def test_la_edad_del_texto_no_se_pregunta(texto, gid):
    sesion = nueva()
    r = enviar(sesion, texto)
    assert sesiones[sesion]["grupo"] == gid
    assert any(l.startswith(f"Grupo de edad: {gid}") for l in r["traza"])
    assert "grupo_edad" not in preguntas_hasta_el_final(sesion, "Persona de 5 a 59 años")      # no vuelve a preguntar


def test_mi_hijo_de_3_anos_tiene_fiebre_no_vuelve_a_preguntar_la_edad():
    sesion = nueva()
    r = enviar(sesion, "mi hijo de 3 años tiene fiebre")
    preguntas = [sesiones[sesion]["pendiente"]]
    while sesiones[sesion]["pendiente"]:
        enviar(sesion, "no")
        preguntas.append(sesiones[sesion]["pendiente"])
    assert "grupo_edad" not in preguntas and "Para quién" not in r["mensaje"]


@pytest.mark.parametrize("texto", ["hace 3 años tuve covid y ahora tengo fiebre", "tengo 5 meses de embarazo y fiebre", "tengo fiebre hace 3 días"])
def test_numeros_que_no_son_la_edad_no_cuentan(texto):
    assert edad.reconocer(texto)[0] is None


def test_el_embarazo_implica_persona_de_5_a_59():
    sesion = nueva()
    r = enviar(sesion, "estoy embarazada y tengo fiebre")
    assert sesiones[sesion]["grupo"] == "persona_5_59" and any("embarazo implica" in l for l in r["traza"])
    assert "grupo_edad" not in preguntas_hasta_el_final(sesion) and "embarazo" in sesiones[sesion]["presentes"]


def test_el_texto_vago_sobre_edad_no_fija_el_grupo():
    assert edad.reconocer("mi hijo tiene fiebre")[0] is None and edad.reconocer("el niño tiene tos")[0] is None
    assert kw.extraer("mi hijo tiene fiebre").presentes == {"fiebre"}


# ---------- la partición ----------
def test_los_grupos_de_edad_son_una_particion():
    assert verificacion.i14_particion_edades(datos.grupos_edad(), set(datos.factores())) == []
    assert verificacion.verificar()["restricciones"]["I14"] is True


def test_toda_edad_cae_en_un_grupo_y_solo_uno():
    for meses in list(range(0, 1500)):
        pertenece = [g for g, x in datos.grupos_edad().items()
                     if x["desde_meses"] <= meses and (x["hasta_meses"] is None or meses < x["hasta_meses"])]
        assert len(pertenece) == 1 and edad.grupo_de_meses(meses) == pertenece[0], meses
    assert [edad.grupo_de_meses(m) for m in (0, 5, 6, 59, 60, 719, 720, 1500)] == [
        "bebe_menor_6m", "bebe_menor_6m", "nino_menor_5", "nino_menor_5", "persona_5_59", "persona_5_59",
        "persona_60_mas", "persona_60_mas"]


def _g(d, h, lit=(), no=()):
    return {"etiqueta": "x", "desde_meses": d, "hasta_meses": h, "literales": list(lit), "no_aplica": list(no), "claves": []}


@pytest.mark.parametrize("grupos, texto", [
    ({"a": _g(0, 12), "b": _g(6, None)}, "se traslapan"),                       # no disjuntos
    ({"a": _g(0, 6), "b": _g(12, None)}, "ningún grupo cubre las edades entre 6 y 12"),          # hueco
    ({"a": _g(0, 6), "b": _g(6, 100)}, "desde 100 meses en adelante"),                           # no llega al infinito
    ({"a": _g(6, None)}, "entre 0 y 6"),                                         # no empieza en 0
    ({"a": _g(10, 5), "b": _g(0, None)}, "intervalo vacío o invertido"),
    ({"a": _g(0, None, lit=["inventado"])}, "'inventado', que no existe"),
])
def test_i14_detecta_particiones_rotas(grupos, texto):
    problemas = verificacion.i14_particion_edades(grupos, {"menor_5"})
    assert problemas and any(texto in p for p in problemas), problemas


def test_i14_acepta_una_particion_valida_minima():
    assert verificacion.i14_particion_edades({"a": _g(0, 100), "b": _g(100, None)}, set()) == []


# ---------- mensajes incompletos ----------
def test_tengo_dolor_pregunta_donde_y_pecho_da_alarma():
    sesion = nueva()
    r = enviar(sesion, "tengo dolor")
    assert r["mensaje"] == "¿Dónde te duele?" and r["estado"] == "TRIAJE"
    assert etiquetas(r) == ["Pecho", "Cabeza", "Garganta", "Barriga", "Cuerpo/músculos", "Detrás de los ojos", "Otro lugar"]
    assert any("Mensaje incompleto" in l for l in r["traza"]) and any("δ(SALUDO, incompleto) = TRIAJE" in l for l in r["traza"])
    r = enviar(sesion, "Pecho")
    assert r["urgencia"] == "urgencia_alta" and tiene_accion(r, "ubicacion")            # alarma


@pytest.mark.parametrize("texto", ["me duele", "tengo una molestia", "siento dolor", "me duele mucho"])
def test_otras_formas_de_dolor_sin_sitio_preguntan_donde(texto):
    assert enviar(nueva(), texto)["mensaje"] == "¿Dónde te duele?"


@pytest.mark.parametrize("texto", ["me siento mal", "tengo malestar", "me siento mal desde ayer"])
def test_me_siento_mal_pregunta_que_sientes(texto):
    r = enviar(nueva(), texto)
    assert r["mensaje"] == "¿Qué sientes?"
    assert etiquetas(r) == ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Vómitos", "Dolor de cabeza", "Cansancio", "Otro síntoma"]


@pytest.mark.parametrize("texto", ["me duele la cabeza", "tengo dolor de garganta", "me duele el pecho", "tengo malestar y fiebre"])
def test_si_hay_un_sintoma_reconocido_no_es_incompleto(texto):
    r = enviar(nueva(), texto)
    assert r["mensaje"] not in ("¿Dónde te duele?", "¿Qué sientes?") and not any("Mensaje incompleto" in l for l in r["traza"])


@pytest.mark.parametrize("etiqueta, sintoma", [
    ("Pecho", "dolor_pecho"), ("Cabeza", "dolor_cabeza"), ("Garganta", "dolor_garganta"), ("Barriga", "dolor_abdominal"),
    ("Cuerpo/músculos", "dolor_muscular"), ("Detrás de los ojos", "dolor_ojos"),
    ("Fiebre", "fiebre"), ("Tos", "tos"), ("Dolor de garganta", "dolor_garganta"), ("Diarrea", "diarrea"), ("Vómitos", "vomitos"),
    ("Dolor de cabeza", "dolor_cabeza"), ("Cansancio", "cansancio"),
])
def test_cada_boton_de_aclaracion_se_entiende_como_su_sintoma(etiqueta, sintoma):
    assert sintoma in kw.extraer(etiqueta).presentes


def test_los_botones_de_aclaracion_y_atajos_son_los_pedidos():
    assert dialogo.ATAJOS == ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Dolor de cabeza", "Otro síntoma"]
    assert dialogo.DONDE[0] == "Pecho" and len(dialogo.DONDE) == 7                    # pecho primero: es alarma


def test_otro_lugar_u_otro_sintoma_pide_que_lo_cuente_con_sus_palabras():
    sesion = nueva()
    enviar(sesion, "tengo dolor")
    r = enviar(sesion, "Otro lugar")
    assert r["mensaje"] == "Cuéntame con tus palabras qué sientes." and rapidas(r) == []
    r = enviar(nueva(), "Otro síntoma")
    assert r["mensaje"] == "Cuéntame con tus palabras qué sientes."
    r2 = enviar(sesion, "me duele la rodilla izquierda")                                # sigue sin reconocerse
    assert r2["mensaje"]


def test_si_sigue_sin_decir_el_sitio_se_repite_la_aclaracion():
    sesion = nueva()
    enviar(sesion, "tengo dolor")
    assert enviar(sesion, "asdfgh")["mensaje"] == "¿Dónde te duele?"


def test_la_aclaracion_se_cierra_cuando_llega_un_sintoma():
    sesion = nueva()
    enviar(sesion, "tengo dolor")
    r = enviar(sesion, "Cabeza")
    assert sesiones[sesion]["aclaracion"] is None and "dolor_cabeza" in sesiones[sesion]["presentes"]
    assert r["estado"] == "TRIAJE" and sesiones[sesion]["pendiente"] == "dificultad_respirar"


def test_dolor_despues_de_una_conclusion_empieza_una_consulta_nueva():
    sesion = nueva()
    hasta_conclusion(sesion, "tengo fiebre, tos y dolor de cuerpo")
    r = enviar(sesion, "tengo dolor")
    assert r["traza"][0] == "Nueva consulta" and r["mensaje"] == "¿Dónde te duele?"


# ---------- saludo con atajos, ayuda y botones sin «(sí / no)» ----------
def test_el_saludo_trae_atajos():
    r = enviar(nueva(), "")
    assert etiquetas(r) == ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Dolor de cabeza", "Otro síntoma"]
    assert "Cuéntame con tus palabras" in r["mensaje"]


@pytest.mark.parametrize("atajo, sintoma", [("Fiebre", "fiebre"), ("Tos", "tos"), ("Dolor de garganta", "dolor_garganta"),
                                            ("Diarrea", "diarrea"), ("Dolor de cabeza", "dolor_cabeza")])
def test_tocar_un_atajo_inicia_el_triaje(atajo, sintoma):
    sesion = nueva()
    r = enviar(sesion, atajo)
    assert r["estado"] == "TRIAJE" and sintoma in sesiones[sesion]["presentes"]


def test_la_ayuda_dice_que_no_esta_seguro_y_ofrece_atajos():
    r = enviar(nueva(), "asdfgh")
    assert r["mensaje"] == "No estoy seguro de haber entendido. ¿Alguno de estos se parece a lo que sientes?"
    assert etiquetas(r) == ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Dolor de cabeza", "Otro síntoma"]
    assert "No reconocí síntomas" not in r["mensaje"]


def test_si_hay_opciones_el_texto_no_dice_si_no():
    sesion = nueva()
    r = enviar(sesion, "tengo fiebre")
    revisadas = 0
    for _ in range(40):
        assert r["opciones"] and SIN_SI_NO not in r["mensaje"]
        revisadas += 1
        pendiente = sesiones[sesion]["pendiente"]
        if pendiente is None:
            break
        r = enviar(sesion, respuesta_a(pendiente))
    assert revisadas >= 8


def test_las_respuestas_a_los_botones_sin_si_no_se_siguen_entendiendo():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = enviar(sesion, "No")                                     # el botón «No»
    assert any(l.startswith("Respuesta a 'dificultad_respirar': no") for l in r["traza"])
