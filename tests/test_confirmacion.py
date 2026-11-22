"""Confirmación antes de concluir: resumen con nombres legibles, corrección y la excepción de seguridad (alarma)."""
import pytest

from app import datos
from app.main import sesiones
from app.motor import dialogo, fsm
from tests.ayudas import enviar, nueva, respuesta_a, tiene_accion, etiquetas


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


def hasta_el_resumen(sesion, primero="tengo fiebre", si=("dolor_ojos", "dolor_muscular")):
    """Responde el triaje y devuelve la respuesta que pide confirmar (sin confirmarla)."""
    r = enviar(sesion, primero)
    for _ in range(40):
        pendiente = sesiones[sesion]["pendiente"]
        if pendiente is None:
            break
        r = enviar(sesion, respuesta_a(pendiente, si))
    assert sesiones[sesion]["confirmando"], "no llegó al resumen"
    return r


# ---------- el flujo normal pasa por la confirmación ----------
def test_el_flujo_normal_pide_confirmar_antes_de_concluir():
    sesion = nueva()
    r = hasta_el_resumen(sesion)
    assert r["urgencia"] is None and r["resultado"] is None and r["estado"] == "TRIAJE"      # todavía no concluyó
    assert r["mensaje"].startswith("Entendí que tienes: ") and r["mensaje"].endswith("¿Es correcto?")
    assert etiquetas(r) == ["Sí, es correcto", "Corregir"]
    assert any("se pide confirmar el resumen antes de concluir" in l for l in r["traza"])


def test_el_resumen_usa_nombres_legibles_y_nunca_ids():
    r = hasta_el_resumen(nueva())
    m = r["mensaje"]
    assert "fiebre" in m and "dolor detrás de los ojos" in m and "dolor de cuerpo o músculos" in m
    assert "y que NO tienes: " in m and "dificultad para respirar" in m and "dolor en el pecho" in m
    assert "La consulta es para: persona de 5 a 59 años." in m
    for id_ in ("dolor_ojos", "dolor_muscular", "dificultad_respirar", "dolor_pecho", "fiebre_persistente", "enfermedad_cronica"):
        assert id_ not in m
    assert "_" not in m


def test_confirmar_concluye_con_la_misma_inferencia():
    sesion = nueva()
    hasta_el_resumen(sesion)
    r = enviar(sesion, "Sí, es correcto")
    assert r["cuadros"] == ["dengue"] and r["urgencia"] == "urgencia_media" and r["estado"] == "SEGURO"
    assert any("El usuario confirma el resumen" in l for l in r["traza"])
    assert any(l.startswith("Mealy: δ(TRIAJE, confirmar) = DERIVACION") for l in r["traza"])


@pytest.mark.parametrize("texto", ["Sí, es correcto", "si", "sí", "correcto", "sip"])
def test_varias_formas_de_confirmar(texto):
    sesion = nueva()
    hasta_el_resumen(sesion)
    assert enviar(sesion, texto)["urgencia"] == "urgencia_media"


def test_si_el_usuario_escribe_algo_que_no_entiende_se_repite_el_resumen():
    sesion = nueva()
    hasta_el_resumen(sesion)
    r = enviar(sesion, "asdfgh")
    assert "Perdona, no te entendí." in r["mensaje"] and "¿Es correcto?" in r["mensaje"] and sesiones[sesion]["confirmando"]


def test_el_limite_de_turnos_tambien_pasa_por_la_confirmacion():
    from app.main import MAX_TURNOS
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    for _ in range(MAX_TURNOS + 1):
        enviar(sesion, "mmm")
        if sesiones[sesion]["confirmando"]:
            break
    assert sesiones[sesion]["confirmando"]


# ---------- excepción de seguridad: con alarma NO se confirma ----------
@pytest.mark.parametrize("texto", ["me duele el pecho", "no puedo respirar", "tengo dolor de pecho y fiebre"])
def test_con_alarma_no_se_pide_confirmacion(texto):
    sesion = nueva()
    r = enviar(sesion, texto)
    assert r["urgencia"] == "urgencia_alta" and not sesiones[sesion]["confirmando"]
    assert "¿Es correcto?" not in r["mensaje"] and tiene_accion(r, "ubicacion")


def test_alarma_dicha_en_una_respuesta_deriva_sin_confirmar():
    sesion = nueva()
    enviar(sesion, "tengo fiebre")
    r = enviar(sesion, "sí")                                  # «¿Te cuesta respirar?» → sí
    assert r["urgencia"] == "urgencia_alta" and not sesiones[sesion]["confirmando"] and "¿Es correcto?" not in r["mensaje"]


def test_alarma_mientras_se_confirma_deriva_de_inmediato():
    sesion = nueva()
    hasta_el_resumen(sesion)
    r = enviar(sesion, "ahora me duele el pecho")
    assert r["urgencia"] == "urgencia_alta" and not sesiones[sesion]["confirmando"]


def test_urgencia_alta_por_regla_tampoco_se_confirma():
    """Diarrea con deshidratación (regla U7) es urgencia alta: se deriva sin pedir confirmación."""
    sesion = nueva()
    enviar(sesion, "tengo diarrea y boca seca")
    r = None
    for _ in range(30):
        p = sesiones[sesion]["pendiente"]
        if p is None:
            break
        r = enviar(sesion, respuesta_a(p, ("vomitos",)))
        if r["urgencia"]:
            break
    assert r["urgencia"] == "urgencia_alta" and not sesiones[sesion]["confirmando"]


# ---------- corregir ----------
def test_corregir_muestra_un_boton_quitar_por_sintoma_y_agregar():
    sesion = nueva()
    hasta_el_resumen(sesion)
    r = enviar(sesion, "Corregir")
    assert r["mensaje"] == "¿Qué quieres corregir?"
    assert etiquetas(r) == ["Quitar dolor de cuerpo o músculos", "Quitar dolor detrás de los ojos", "Quitar fiebre", "Agregar otro síntoma"]
    assert sesiones[sesion]["correccion_modo"] == "elegir" and sesiones[sesion]["confirmando"]
    assert not any("_" in e for e in etiquetas(r))


def test_quitar_un_sintoma_cambia_el_cuadro_inferido():
    # con los tres síntomas, el cuadro es dengue
    sesion = nueva()
    hasta_el_resumen(sesion)
    assert enviar(sesion, "Sí, es correcto")["cuadros"] == ["dengue"]
    # quitando «dolor detrás de los ojos», la regla R3 ya no se cumple
    sesion = nueva()
    hasta_el_resumen(sesion)
    enviar(sesion, "Corregir")
    r = enviar(sesion, "Quitar dolor detrás de los ojos")
    assert "Listo, quité «dolor detrás de los ojos»." in r["mensaje"]
    assert "dolor_ojos" in sesiones[sesion]["ausentes"] and "dolor_ojos" not in sesiones[sesion]["presentes"]
    assert any("Corrección: quito «dolor detrás de los ojos»" in l for l in r["traza"])
    for _ in range(20):                                           # vuelve a razonar: puede hacer preguntas nuevas
        p = sesiones[sesion]["pendiente"]
        if p is None:
            break
        r = enviar(sesion, respuesta_a(p))
    assert sesiones[sesion]["confirmando"]
    assert "dolor detrás de los ojos" in r["mensaje"].split("NO tienes: ")[1]            # ahora figura entre lo que NO tiene
    final = enviar(sesion, "Sí, es correcto")
    assert "dengue" not in final["cuadros"] and final["cuadros"] != ["dengue"]


def test_quitar_fiebre_anula_su_duracion():
    sesion = nueva()
    hasta_el_resumen(sesion)
    assert "duracion_fiebre" in sesiones[sesion]["respondidas"]
    enviar(sesion, "Corregir")
    enviar(sesion, "Quitar fiebre")
    assert "fiebre" in sesiones[sesion]["ausentes"] and "duracion_fiebre" not in sesiones[sesion]["respondidas"]
    assert not ({"fiebre_persistente"} & (sesiones[sesion]["presentes"] | sesiones[sesion]["ausentes"]))


def test_agregar_otro_sintoma_sigue_el_triaje_y_vuelve_a_confirmar():
    sesion = nueva()
    hasta_el_resumen(sesion)
    enviar(sesion, "Corregir")
    r = enviar(sesion, "Agregar otro síntoma")
    assert r["mensaje"] == dialogo.MENSAJE_ACLARAR["agregar"] and "Tos" in etiquetas(r)
    assert sesiones[sesion]["aclaracion"] == "agregar"
    r = enviar(sesion, "Dolor de garganta")
    assert "dolor_garganta" in sesiones[sesion]["presentes"]
    for _ in range(20):
        p = sesiones[sesion]["pendiente"]
        if p is None:
            break
        r = enviar(sesion, respuesta_a(p))
    assert sesiones[sesion]["confirmando"] and "dolor de garganta" in r["mensaje"].split("NO tienes")[0]


def test_despues_de_corregir_se_vuelve_a_confirmar_y_se_puede_concluir():
    sesion = nueva()
    hasta_el_resumen(sesion)
    enviar(sesion, "Corregir")
    enviar(sesion, "Quitar dolor de cuerpo o músculos")
    for _ in range(20):
        p = sesiones[sesion]["pendiente"]
        if p is None:
            break
        enviar(sesion, respuesta_a(p))
    assert sesiones[sesion]["confirmando"]
    assert enviar(sesion, "Sí, es correcto")["urgencia"] is not None


def test_las_correcciones_tienen_tope():
    """Después de MAX_CORRECCIONES solo se ofrece confirmar: el diálogo siempre termina."""
    sesion = nueva()
    hasta_el_resumen(sesion)
    for _ in range(dialogo.MAX_CORRECCIONES):
        enviar(sesion, "Corregir")
        enviar(sesion, "Agregar otro síntoma")
        enviar(sesion, "Tos")
        for _ in range(20):
            p = sesiones[sesion]["pendiente"]
            if p is None:
                break
            enviar(sesion, respuesta_a(p))
        assert sesiones[sesion]["confirmando"]
    assert sesiones[sesion]["correcciones"] == dialogo.MAX_CORRECCIONES
    r = enviar(sesion, "Corregir")
    assert etiquetas(r) == ["Sí, es correcto"] and "Nueva consulta" in r["mensaje"]
    assert enviar(sesion, "Sí, es correcto")["urgencia"] is not None


def test_el_tope_de_correcciones_es_el_pedido():
    assert dialogo.MAX_CORRECCIONES == 3


# ---------- el texto del resumen ----------
def test_texto_resumen_con_nombres():
    t = dialogo.texto_resumen({"fiebre", "tos"}, {"dolor_pecho"}, "Persona de 60 años o más")
    assert t == ("Entendí que tienes: fiebre, tos, y que NO tienes: dolor en el pecho. "
                 "La consulta es para: persona de 60 años o más. ¿Es correcto?")
    assert dialogo.texto_resumen(set(), set(), None) == "Entendí que no mencionaste síntomas. ¿Es correcto?"
    assert "menor_5" not in dialogo.texto_resumen({"menor_5", "fiebre"}, {"mayor_60"}, None)       # los literales de edad no se listan


def test_todos_los_sintomas_y_factores_tienen_nombre_legible():
    nombres = datos.cargar("nombres")["nombres"]
    for id_ in list(datos.sintomas()) + list(datos.factores()):
        assert id_ in nombres and "_" not in nombres[id_], id_


# ---------- Mealy ----------
def test_confirmar_y_corregir_estan_en_sigma_y_delta_sigue_total():
    assert {"confirmar", "corregir"} <= set(fsm.SIGMA) and fsm.es_total()
    assert fsm.paso("TRIAJE", "confirmar") == ("DERIVACION", "concluir")
    assert fsm.paso("TRIAJE", "corregir") == ("TRIAJE", "corregir")
    for q in fsm.Q:
        for s in ("confirmar", "corregir"):
            assert (q, s) in fsm.DELTA
