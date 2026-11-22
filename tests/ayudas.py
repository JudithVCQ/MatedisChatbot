"""Ayudas compartidas por las pruebas de la conversación (el flujo es: triaje → seguro → ubicación → ruta)."""
import uuid

from fastapi.testclient import TestClient

from app.main import app, peticiones, sesiones

cliente = TestClient(app)

UNMSM = (-12.056, -77.084)
KENNEDY = (-12.1211, -77.0297)
LINCE = (-12.08312, -77.03488)
SAN_JUAN_DE_MIRAFLORES = (-12.160, -76.970)
AREQUIPA = (-16.40, -71.53)
MAR_DENTRO_DEL_CIRCULO = (-12.10, -77.12)     # océano, dentro del radio de cobertura pero a más de 1500 m de toda calle
NO_RUTA = "No pude calcular la ruta. Ante una emergencia llama al SAMU 106."


def nueva() -> str:
    return uuid.uuid4().hex


def enviar(sesion: str, mensaje: str = "", punto=None, **extra) -> dict:
    """Una petición al chat. `punto` = (lat, lng) de la ubicación compartida en ESTA petición."""
    peticiones.clear()        # una prueba hace varias peticiones: se vacía el limitador
    cuerpo = {"sesion": sesion, "mensaje": mensaje, **extra}
    if punto is not None:
        cuerpo["lat"], cuerpo["lng"] = punto
    r = cliente.post("/api/chat", json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


GRUPO_POR_DEFECTO = "Persona de 5 a 59 años"
# Preguntas de opciones: salvo que la prueba diga otra cosa, la respuesta menos alarmante.
RESPUESTA_POR_DEFECTO = {"duracion_fiebre": "Hoy", "intensidad_dolor_abdominal": "Leve"}


def respuesta_a(pendiente: str, si=(), grupo: str = GRUPO_POR_DEFECTO, opciones: dict | None = None) -> str:
    """Qué contestar a la pregunta pendiente: la edad se elige entre sus opciones; las demás, sí/no."""
    if pendiente == "grupo_edad":
        return grupo
    if opciones and pendiente in opciones:
        return opciones[pendiente]
    if pendiente in RESPUESTA_POR_DEFECTO:
        return RESPUESTA_POR_DEFECTO[pendiente]
    return "si" if pendiente in si else "no"


def confirmar_si_toca(sesion: str, r: dict) -> dict:
    """Si el triaje terminó en el resumen («¿Es correcto?»), lo confirma y devuelve la respuesta de la conclusión."""
    if sesiones[sesion]["confirmando"]:
        return enviar(sesion, "Sí, es correcto")
    return r


def hasta_conclusion(sesion: str, primero: str, si=(), grupo: str = GRUPO_POR_DEFECTO, opciones: dict | None = None) -> dict:
    """Envía `primero`, responde las preguntas del triaje ('sí' solo a las de `si`; la edad con `grupo`) y confirma el
    resumen. Devuelve la respuesta de la conclusión."""
    r = enviar(sesion, primero)
    for _ in range(40):
        pendiente = sesiones[sesion]["pendiente"]
        if pendiente is None:
            return confirmar_si_toca(sesion, r)
        r = enviar(sesion, respuesta_a(pendiente, si, grupo, opciones))
    raise AssertionError("el triaje no terminó")


def emergencia(sesion: str) -> dict:
    return enviar(sesion, "me duele el pecho")


def media(sesion: str) -> dict:
    return hasta_conclusion(sesion, "tengo fiebre", {"dolor_ojos", "dolor_muscular"})        # dengue


def baja(sesion: str) -> dict:
    return hasta_conclusion(sesion, "tengo fiebre, tos y dolor de cuerpo")                    # gripe


AUXILIARES = ("deshacer", "por_que")       # botones pequeños («Me equivoqué», «¿Por qué?»): no son respuestas rápidas


def rapidas(respuesta: dict) -> list[dict]:
    """Las respuestas rápidas de una respuesta (sin los botones auxiliares)."""
    return [o for o in respuesta["opciones"] if o["accion"] not in AUXILIARES]


def etiquetas(respuesta: dict) -> list[str]:
    return [o["etiqueta"] for o in rapidas(respuesta)]


def tiene_accion(respuesta: dict, accion: str) -> bool:
    return any(o["accion"] == accion for o in respuesta["opciones"])


def ruta_de_emergencia(punto, sesion: str | None = None) -> dict:
    """Emergencia y luego la ubicación: devuelve la respuesta con la ruta."""
    sesion = sesion or nueva()
    emergencia(sesion)
    return enviar(sesion, "", punto=punto)
