"""Backend FastAPI. Orquesta: extractor → Mealy → árbol → motor lógico → seguro → ubicación → Dijkstra."""
import copy
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.datos import cargar, ids_alarma, lexico, niveles, nombre, pregunta, preguntas_especiales
from app.datos import zona as datos_zona
from app.motor import (arbol, dialogo, edad, extractor, fichas, fsm, grafo, inferencia, medidas, preguntas, red_vial,
                       relaciones, ruteo, seguros, verificacion)
from app.motor.extractor_keywords import es_si, normalizar
from app.schemas import ChatRequest, ChatResponse, EstablecimientoResultado, Opcion, Resultado

load_dotenv()  # lee .env en local; en Render se usan sus variables de entorno
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("triaje")

MAX_TURNOS = 12           # > altura total del árbol (11: 9 + 2 seguimientos): la conversación siempre termina (restricción I10)
MAX_PETICIONES_MIN = 30   # por IP
MAX_PILA = 20             # cuántos pasos se pueden deshacer
AVISO = "Esto es orientación, no un diagnóstico. Ante una emergencia llama al SAMU 106."
LEY_EMERGENCIAS = "Por ley, toda emergencia debe ser atendida en cualquier establecimiento, sin importar tu seguro (Ley 27604)."
NO_RUTA = "No pude calcular la ruta. Ante una emergencia llama al SAMU 106."
PRIVACIDAD_UBICACION = "La uso solo para calcular la ruta y no se guarda."


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """Al arrancar se comprueban las restricciones de integridad I1–I14; si alguna falla, el servidor no arranca."""
    resultado = verificacion.verificar(MAX_TURNOS)
    if not resultado["consistente"]:
        raise RuntimeError("Base de conocimiento inconsistente: " + "; ".join(resultado["problemas"]))
    red = red_vial.cargar_red()   # se carga al arrancar para que la primera consulta no espere
    log.info("red vial: %s", f"{len(red.nodos)} nodos" if red else "no hay red_lima.json; se usa el grafo de distritos")
    yield


app = FastAPI(title="TriajeLógico", version="0.1.0", lifespan=ciclo_de_vida)
STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Sesiones solo en memoria: no se guarda nada en disco ni en base de datos.
# Nunca se guardan coordenadas: la ubicación se usa en la petición que la trae y se descarta.
sesiones: dict[str, dict] = {}
peticiones: dict[str, deque] = defaultdict(deque)


def nueva_sesion(seguro: str | None = None) -> dict:
    """`seguro` se conserva entre consultas: se pregunta una sola vez por sesión."""
    return {"estado": fsm.Q0, "presentes": set(), "ausentes": set(), "pendiente": None, "turnos": 0,
            "seguro": seguro, "seguro_intentos": 0,
            "nivel": None,       # urgencia de la última conclusión
            "centro": None,      # {"nivel": ...} mientras se busca un establecimiento (sin coordenadas)
            "retorno": False,    # el centro se pidió en mitad del triaje: al terminar se vuelve a TRIAJE
            "oferta": False,     # se ofreció un centro de salud (urgencia baja) y se espera sí / no
            "grupo": None,       # grupo de edad (partición de data/grupos_edad.json)
            "no_aplica": set(),  # preguntas que no se hacen a este paciente (p. ej. embarazo a un niño)
            "respondidas": set(),  # preguntas especiales ya contestadas (grupo_edad, ...)
            "aclaracion": None,  # se pidió aclarar un mensaje incompleto: "donde" | "que" | "libre" | "agregar"
            "confirmando": False,    # se mostró el resumen y se espera «Sí, es correcto» o «Corregir»
            "correccion_modo": None,  # "elegir": se muestran los botones «Quitar X» / «Agregar otro síntoma»
            "correccion": None,      # lo que pidió corregir: {"tipo": "mostrar" | "quitar" | "agregar", "id": ...}
            "correcciones": 0,       # cuántas veces corrigió (tope: dialogo.MAX_CORRECCIONES)
            "pila": [],              # estados anteriores de la sesión, para «Me equivoqué» (máximo MAX_PILA)
            "alarma_ultima": False}  # la última respuesta del usuario fue un signo de alarma


# ---------- manejo de errores: el usuario nunca ve una traza ----------
@app.exception_handler(RequestValidationError)
async def entrada_invalida(_: Request, exc: RequestValidationError):
    # Solo campo y tipo de error: nunca el valor recibido (podría ser una coordenada, Ley 29733).
    errores = [(".".join(str(x) for x in e["loc"]), e["type"]) for e in exc.errors()]
    log.info("entrada inválida: %s", errores)
    # El error de ubicación puede venir de un campo (lat/lng) o del validador "lat y lng juntas".
    if any(campo.split(".")[-1] in ("lat", "lng") for campo, _ in errores) or \
            any("lat y lng" in e["msg"] for e in exc.errors()):
        return JSONResponse(status_code=422, content={
            "estado": "ERROR", "codigo": "ubicacion_invalida",
            "mensaje": "Tu ubicación no es válida. Puedes seguir sin compartirla: te daré la recomendación sin ruta."})
    return JSONResponse(status_code=422, content={
        "estado": "ERROR", "mensaje": "No pude leer tu mensaje. Escríbelo de nuevo, en menos de 500 caracteres."})


@app.exception_handler(Exception)
async def error_interno(_: Request, exc: Exception):
    log.exception("error interno: %s", exc)
    return JSONResponse(status_code=500, content={
        "estado": "ERROR", "mensaje": f"Tuvimos un problema. Intenta otra vez. {AVISO}"})


# ---------- rutas ----------
@app.get("/")
def inicio():
    return FileResponse(STATIC / "index.html")


@app.get("/api/salud")
def salud():
    return {"ok": True}


@app.get("/api/zona")
def zona_cobertura():
    """Zona de cobertura (data/zona.json): el front centra el mapa y dibuja el círculo con esto."""
    z = datos_zona()
    return {"centro": z["centro"], "radio_m": z["radio_m"]}


@app.get("/api/grafo")
def grafo_endpoint():
    return grafo.grafo_completo()


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    ip = request.client.host if request.client else "?"
    ahora, cola = time.time(), peticiones[ip]
    while cola and ahora - cola[0] > 60:
        cola.popleft()
    if len(cola) >= MAX_PETICIONES_MIN:
        return ChatResponse(estado="ERROR", mensaje="Demasiados mensajes seguidos. Espera un minuto.")
    cola.append(ahora)
    return procesar(req)


# ---------- botones de respuesta rápida ----------
opciones_si_no = dialogo.opciones_si_no


def opciones_seguro() -> list[Opcion]:
    return [Opcion(etiqueta=o["etiqueta"], valor=o["valor"]) for o in seguros.opciones()]


def opciones_ubicacion(reintento: bool = False) -> list[Opcion]:
    if reintento:
        return [Opcion(etiqueta="Intentar de nuevo", accion="ubicacion")]
    return [Opcion(etiqueta="Compartir mi ubicación", accion="ubicacion"),
            Opcion(etiqueta="Prefiero no compartirla", accion="sin_ubicacion")]


# ---------- Mealy ----------
def paso(s: dict, simbolo: str, traza: list[str], nota: str = "") -> str:
    """Aplica δ, actualiza el estado de la sesión y agrega la transición a la traza. Devuelve la salida λ."""
    anterior = s["estado"]
    s["estado"], salida = fsm.paso(anterior, simbolo)
    traza.append(f"Mealy: δ({anterior}, {simbolo}) = {s['estado']}  /  λ = {salida}" + (f"  ({nota})" if nota else ""))
    return salida


def ausentes_arbol(s: dict) -> set[str]:
    """Lo que el árbol da por resuelto: lo negado, lo que no aplica a este paciente y las preguntas especiales ya contestadas."""
    return s["ausentes"] | s["no_aplica"] | s["respondidas"]


def aplicar_grupo(s: dict, gid: str, traza: list[str], motivo: str) -> None:
    """Fija el grupo de edad y genera los literales que usan las reglas. La partición garantiza que es uno solo."""
    s["grupo"] = gid
    literales = edad.literales(gid)
    s["presentes"] |= literales
    s["ausentes"] = (s["ausentes"] | edad.ausentes_de_edad(gid)) - s["presentes"]
    s["no_aplica"] |= edad.no_aplica(gid)
    s["respondidas"].add("grupo_edad")
    traza.append(f"Grupo de edad: {gid} ({motivo}) → literales {sorted(literales) or 'ninguno'}"
                 + (f"; no se preguntará: {sorted(edad.no_aplica(gid))}" if edad.no_aplica(gid) else ""))


def responder_especial(s: dict, id_: str, texto: str, traza: list[str]) -> bool:
    """Contesta una pregunta especial (no sí/no). Devuelve True si el texto la respondió."""
    especial = preguntas_especiales()[id_]
    if especial["tipo"] == "grupo":
        gid, motivo = edad.reconocer(texto)
        if gid is None:
            return False
        if s["grupo"] is None:
            aplicar_grupo(s, gid, traza, motivo)
        return True
    opcion = preguntas.reconocer_opcion(id_, texto, medidas.dias(texto))
    if opcion is None:
        return False
    aplicar_opcion(s, id_, opcion, traza, "respuesta a la pregunta")
    return True


def aplicar_opcion(s: dict, id_: str, opcion: dict, traza: list[str], motivo: str) -> None:
    """Aplica los efectos de la opción elegida: literales que pasan a presentes o ausentes."""
    efecto = opcion.get("efecto", {})
    presentes, ausentes = set(efecto.get("presentes", [])), set(efecto.get("ausentes", []))
    s["presentes"] |= presentes
    s["ausentes"] = (s["ausentes"] | ausentes) - s["presentes"]
    s["respondidas"].add(id_)
    traza.append(f"Respuesta a '{id_}': «{opcion['etiqueta']}» ({motivo}) → presentes {sorted(presentes) or 'ninguno'}, "
                 f"ausentes {sorted(ausentes) or 'ninguno'}")


def deducir_medidas(s: dict, texto: str, traza: list[str]) -> bool:
    """Temperatura ("39 de fiebre", "38.5 grados": desde 38 °C es fiebre) y días ("hace 4 días") del texto libre."""
    aprendio = False
    grados = medidas.temperatura(texto)
    if grados is not None:
        if medidas.es_fiebre(grados):
            traza.append(f"Temperatura {grados:g} °C ≥ {medidas.UMBRAL_FIEBRE_C:g} °C: cuenta como fiebre")
            s["presentes"].add("fiebre")
            s["ausentes"].discard("fiebre")
            aprendio = True
        elif "fiebre" in s["presentes"]:
            traza.append(f"Temperatura {grados:g} °C: menor que {medidas.UMBRAL_FIEBRE_C:g} °C, pero el texto dice fiebre: se respeta")
        else:
            traza.append(f"Temperatura {grados:g} °C: menor que {medidas.UMBRAL_FIEBRE_C:g} °C, no cuenta como fiebre")
    if "fiebre" in s["presentes"] and "duracion_fiebre" not in s["respondidas"]:
        dias = medidas.dias(texto)
        opcion = preguntas.opcion_por_dias("duracion_fiebre", dias) if dias is not None else None
        if opcion:
            aplicar_opcion(s, "duracion_fiebre", opcion, traza, f"duración detectada en el texto: {dias} días")
            aprendio = True
    return aprendio


def deducir_edad(s: dict, texto: str, traza: list[str]) -> bool:
    """Si el texto ya trae la edad ("mi hijo de 3 años") no se vuelve a preguntar. Devuelve True si aprendió algo."""
    if s["grupo"] is not None:
        return False
    gid, motivo = edad.reconocer(texto)
    if gid is None and "embarazo" in s["presentes"]:
        gid, motivo = "persona_5_59", "el embarazo implica una persona de 5 a 59 años"
    if gid is None:
        return False
    aplicar_grupo(s, gid, traza, motivo)
    return True


def clasificar_confirmacion(s: dict, texto: str, traza: list[str]) -> str | None:
    """Respuesta al resumen («¿Es correcto?»): confirmar, corregir o None (si trae otra cosa, p. ej. más síntomas)."""
    normal = normalizar(texto).strip()
    if s["correccion_modo"] == "elegir":
        if normal == normalizar(dialogo.AGREGAR):
            s["correccion"] = {"tipo": "agregar"}
            return "corregir"
        for id_ in dialogo.corregibles(s["presentes"]):
            if normal == normalizar(dialogo.texto_quitar(id_)):
                s["correccion"] = {"tipo": "quitar", "id": id_}
                return "corregir"
    respuesta = es_si(texto)
    if respuesta is True:
        traza.append("El usuario confirma el resumen")
        return "confirmar"
    if respuesta is False or any(f in normal for f in lexico()["corregir"]):
        s["correccion"] = {"tipo": "mostrar"}
        traza.append("El usuario quiere corregir el resumen")
        return "corregir"
    return None


def clasificar(req: ChatRequest, s: dict, texto: str, traza: list[str]) -> str:
    """Clasifica la entrada en un símbolo de Σ. Aquí se consumen también el seguro y la ubicación."""
    estado = s["estado"]

    # La ubicación solo cuenta si se pidió (o si es un reintento): se ignora si llega sin haberla pedido.
    if req.lat is not None or req.ubicacion_denegada:
        if estado == "UBICACION" or (estado in ("DERIVACION", "TRIAJE") and s["centro"]):
            return "ubicacion"
        traza.append("Ubicación recibida sin haberla pedido: se ignora")
    if not texto:
        return "vacio"

    extr, fuente = extractor.extraer(texto)
    traza += extr.correcciones                    # "Corregí 'fievre' → 'fiebre' (distancia 1)"
    traza.append(f"Extractor ({fuente}): presentes={sorted(extr.presentes)} ausentes={sorted(extr.ausentes)}")
    con_sintomas = bool(extr.presentes or extr.ausentes)
    alarma = extractor.hay_alarma(extr)

    if estado == "SEGURO" and not alarma:
        sid = seguros.reconocer(texto)
        if sid:
            s["seguro"], s["seguro_intentos"] = sid, 0
            traza.append(f"Seguro reconocido: {sid}")
            return "seguro"
        if seguros.pide_centro(texto):
            return "buscar_centro"
        if not con_sintomas:
            s["seguro_intentos"] += 1
            if s["seguro_intentos"] >= 2:
                s["seguro"] = "no_se"
                traza.append("No reconocí el seguro dos veces: se asume 'no sé'")
                return "seguro"
            return "invalido"
    if estado in ("SEGURO", "UBICACION") and con_sintomas and not alarma and s["retorno"]:
        # llegaron síntomas en mitad del triaje: se cancela la consulta del centro y se sigue con el triaje
        s["estado"], s["retorno"], s["centro"] = "TRIAJE", False, None
        estado = "TRIAJE"
        traza.append("Llegaron síntomas: se cancela la consulta del centro y se vuelve al triaje")
    if estado == "UBICACION" and not con_sintomas and not alarma:
        return "buscar_centro" if seguros.pide_centro(texto) else "invalido"

    # Resumen pendiente de confirmar: «Sí, es correcto» / «Corregir» (la alarma ya se atendió arriba: nunca se confirma)
    if estado == "TRIAJE" and s["confirmando"] and not alarma:
        simbolo = clasificar_confirmacion(s, texto, traza)
        if simbolo:
            return simbolo

    # Oferta de un centro de salud (urgencia baja): sí / no
    if s["oferta"] and not alarma:
        r = es_si(texto)
        if r is not None:
            s["oferta"] = False
            traza.append(f"Respuesta a la oferta de un centro de salud: {'sí' if r else 'no'}")
            if r:
                return "seguro" if s["seguro"] else "buscar_centro"
            return "respuesta"

    # El usuario pide un establecimiento ("¿dónde me atiendo?", "hospital cerca"...)
    if not alarma and seguros.pide_centro(texto):
        traza.append("El usuario pide un establecimiento")
        return "seguro" if (s["seguro"] or s["nivel"] == "urgencia_alta") else "buscar_centro"

    # Síntomas, edad y respuestas a las preguntas del triaje
    pendiente = s["pendiente"]    # se guarda antes de limpiarlo, para evaluar la alarma de ESTE mensaje
    contestada, alarma_respuesta = False, False
    alarmas_antes = s["presentes"] & ids_alarma()
    if pendiente in preguntas_especiales():
        contestada = responder_especial(s, pendiente, texto, traza)
        alarma_respuesta = bool((s["presentes"] & ids_alarma()) - alarmas_antes)      # p. ej. «Fuerte y no se me pasa»
    elif pendiente:
        r = es_si(texto)
        if r is not None:
            (s["presentes"] if r else s["ausentes"]).add(pendiente)
            traza.append(f"Respuesta a '{pendiente}': {'sí' if r else 'no'}")
            contestada = True
            alarma_respuesta = r and pendiente in ids_alarma()     # solo la alarma de ESTE mensaje cuenta
    if contestada:
        s["pendiente"] = None
    s["presentes"] |= extr.presentes
    s["ausentes"] = (s["ausentes"] | extr.ausentes) - s["presentes"]
    con_edad = deducir_edad(s, texto, traza)
    con_medidas = deducir_medidas(s, texto, traza)
    if alarma or alarma_respuesta:
        return "alarma"
    if contestada:
        return "respuesta"
    if con_sintomas or con_edad or con_medidas:
        s["aclaracion"] = None
        return "sintomas"

    # Mensaje incompleto: dice que algo le pasa pero no qué ("tengo dolor", "me siento mal", «Otro síntoma»)
    if estado in ("SALUDO", "TRIAJE", "ERROR", "DERIVACION"):
        tipo = "libre" if dialogo.es_otro(texto) else dialogo.tipo_incompleto(texto)
        if tipo is None and s["aclaracion"] in ("donde", "que", "agregar"):
            tipo = s["aclaracion"]                       # sigue aclarando: se repite la misma pregunta
        if tipo:
            s["aclaracion"] = tipo
            traza.append(f"Mensaje incompleto: se pregunta {dialogo.MENSAJE_ACLARAR[tipo]!r}")
            return "incompleto"
    return "invalido"


def procesar(req: ChatRequest, nueva_consulta: bool = False) -> ChatResponse:
    """Cuerpo del chat, fuera del limitador de peticiones. Agrega «Me equivoqué» cuando hay algo que deshacer."""
    respuesta = _procesar(req, nueva_consulta)
    s = sesiones.get(req.sesion)
    if s and s["pila"] and not any(o.accion == "deshacer" for o in respuesta.opciones):
        respuesta.opciones = [*respuesta.opciones, dialogo.opcion_deshacer()]
    return respuesta


def _trae_sintomas(texto: str) -> bool:
    """«¿Por qué tengo fiebre?» no es «¿por qué me preguntas esto?»: si hay síntomas, es un mensaje normal."""
    e, _ = extractor.extraer(texto)
    return bool(e.presentes or e.ausentes)


def explicar(s: dict, traza: list[str]) -> ChatResponse:
    """«¿Por qué?»: explica la pregunta pendiente (con relaciones.py) y la repite. NO avanza la conversación: no consume
    turno, no cambia el estado, no apila y no modifica la pregunta pendiente."""
    paso(s, "explicar", traza, "no consume turno")
    id_ = s["pendiente"]
    texto, cuadros = dialogo.explicacion(id_, s["presentes"])
    traza.append(f"Explicación de '{id_}': cuadros candidatos con ese dato en sus reglas → {cuadros or 'ninguno'}")
    pregunta_texto, opciones = dialogo.pregunta_y_opciones(id_)
    return ChatResponse(estado=s["estado"], traza=traza, opciones=opciones, mensaje=f"{texto}\n{pregunta_texto}")


def apilar(s: dict) -> None:
    """Guarda una copia del estado de la sesión ANTES de procesar la respuesta (la pila no se copia a sí misma)."""
    s["pila"].append(copy.deepcopy({k: v for k, v in s.items() if k != "pila"}))
    if len(s["pila"]) > MAX_PILA:
        s["pila"].pop(0)


def deshacer(s: dict, traza: list[str]) -> ChatResponse:
    """«Me equivoqué»: restaura el estado anterior y repite la pregunta de entonces.

    Es una máquina de Mealy EXTENDIDA CON PILA: una máquina de estados finita solo recuerda en qué estado está, no
    cómo llegó; deshacer exige recordar la historia, así que la sesión guarda los últimos MAX_PILA estados."""
    if not s["pila"]:
        paso(s, "deshacer", traza, "pila vacía: no hay nada que deshacer")
        return ChatResponse(estado=s["estado"], traza=traza, mensaje="No hay nada que deshacer.")
    habia_alarma = s["alarma_ultima"]
    actual = s["estado"]
    paso(s, "deshacer", traza)
    anterior, pila = s["pila"].pop(), s["pila"]
    s.clear()
    s.update(anterior)
    s["pila"] = pila
    traza.append(f"Mealy+pila: se restaura el estado {s['estado']} (antes era {actual}); quedan {len(pila)} pasos que deshacer")
    avisos = ["Sin problema, volvamos atrás."]
    if habia_alarma:
        avisos.append(dialogo.AVISO_DESHACER_ALARMA)
        traza.append("Se deshizo una respuesta que había dado alarma: se restaura igual, pero se avisa")
    respuesta = reiterar(s, traza)          # después de la traza: la respuesta copia la lista al construirse
    respuesta.mensaje = " ".join(avisos) + "\n" + respuesta.mensaje
    return respuesta


def reiterar(s: dict, traza: list[str]) -> ChatResponse:
    """Repite la pregunta que correspondía al estado restaurado."""
    estado = s["estado"]
    if estado == "SEGURO":
        return ChatResponse(estado=estado, traza=traza, opciones=opciones_seguro(),
                            mensaje="Para indicarte el centro de salud más cercano, ¿qué seguro tienes?")
    if estado == "UBICACION":
        return ChatResponse(estado=estado, traza=traza, opciones=opciones_ubicacion(), mensaje=texto_pedir_ubicacion(s))
    if estado == "DERIVACION":
        if s["oferta"]:
            return ChatResponse(estado=estado, traza=traza, opciones=opciones_si_no(),
                                mensaje="¿Quieres que te indique un centro de salud cercano por si lo necesitas?")
        return ChatResponse(estado=estado, traza=traza, mensaje="Listo. Cuéntame qué síntomas tienes para empezar de nuevo.")
    if estado == "TRIAJE":
        if s["confirmando"] and s["correccion_modo"] == "elegir":
            return ChatResponse(estado=estado, traza=traza, opciones=dialogo.opciones_quitar(s["presentes"]),
                                mensaje="¿Qué quieres corregir?")
        if s["confirmando"]:
            return pedir_confirmacion(s, traza)
        if s["aclaracion"]:
            return ChatResponse(estado=estado, traza=traza, opciones=dialogo.opciones_aclarar(s["aclaracion"]),
                                mensaje=dialogo.MENSAJE_ACLARAR[s["aclaracion"]])
        pregunta_id = s["pendiente"] or arbol.siguiente_pregunta(s["presentes"], ausentes_arbol(s))
        if pregunta_id is None:
            return pedir_confirmacion(s, traza)
        s["pendiente"] = pregunta_id
        texto, opciones = dialogo.pregunta_y_opciones(pregunta_id)
        return ChatResponse(estado=estado, traza=traza, opciones=opciones, mensaje=texto)
    return ChatResponse(estado=estado, traza=traza, opciones=dialogo.opciones_atajos(), mensaje=f"{dialogo.SALUDO} {AVISO}")


def _procesar(req: ChatRequest, nueva_consulta: bool = False) -> ChatResponse:
    s = sesiones.setdefault(req.sesion, nueva_sesion())
    traza: list[str] = ["Nueva consulta"] if nueva_consulta else []
    anterior = s["estado"]
    texto = req.mensaje.strip()

    if texto and req.lat is None and not req.ubicacion_denegada and dialogo.es_deshacer(texto):
        traza.append("El usuario pide deshacer el último paso")
        return deshacer(s, traza)
    if (texto and s["pendiente"] and req.lat is None and not req.ubicacion_denegada and dialogo.es_por_que(texto)
            and not _trae_sintomas(texto)):
        return explicar(s, traza)
    if texto or req.lat is not None or req.ubicacion_denegada:        # una respuesta del usuario: se guarda el estado
        apilar(s)

    simbolo = clasificar(req, s, texto, traza)
    s["alarma_ultima"] = simbolo == "alarma"
    salida = paso(s, simbolo, traza)

    if salida == "reiniciar":
        sesiones[req.sesion] = nueva_sesion(seguro=s["seguro"])
        if simbolo in ("sintomas", "incompleto"):
            # el mensaje trae síntomas: no se pierde, se procesa como nueva consulta (el seguro se conserva)
            return _procesar(req, nueva_consulta=True)
        return ChatResponse(estado=fsm.Q0, mensaje="Empecemos una nueva consulta. ¿Qué síntomas tienes?", traza=traza)
    if salida == "saludar":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_atajos(),
                            mensaje=f"{dialogo.SALUDO} {AVISO}")
    if salida == "ayuda":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_atajos(), mensaje=dialogo.AYUDA)
    if salida == "aclarar":
        tipo = s["aclaracion"] or "libre"
        return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_aclarar(tipo),
                            mensaje=dialogo.MENSAJE_ACLARAR[tipo])
    if salida == "emergencia":
        # La urgencia ya está decidida (alta); la inferencia solo agrega el cuadro y su traza.
        hechos, pasos, _ = inferencia.inferir(inferencia.literales(s["presentes"], s["ausentes"]))
        traza += pasos
        return derivar(s, "urgencia_alta", traza, cuadros=inferencia.cuadros(hechos), hechos=hechos,
                       motivo="Signo de alarma detectado.")

    # Consulta de un establecimiento: seguro → ubicación → ruta
    if salida in ("pedir_seguro", "pedir_ubicacion") and anterior not in ("SEGURO", "UBICACION"):
        iniciar_centro(s, anterior, traza)
    if salida == "pedir_seguro":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=opciones_seguro(),
                            mensaje="Para indicarte el centro de salud más cercano, ¿qué seguro tienes?")
    if salida == "repetir_seguro":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=opciones_seguro(),
                            mensaje="Perdona, no te entendí. ¿Qué seguro tienes? Elige una opción o escríbelo.")
    if salida == "pedir_ubicacion":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=opciones_ubicacion(),
                            mensaje=texto_pedir_ubicacion(s))
    if salida == "repetir_ubicacion":
        return ChatResponse(estado=s["estado"], traza=traza, opciones=opciones_ubicacion(),
                            mensaje="Necesito tu ubicación para indicarte la ruta. Usa «Compartir mi ubicación» "
                                    "o elige no compartirla y te doy la recomendación sin ruta.")
    if salida == "mostrar_ruta":
        return mostrar_ruta(req, s, traza)
    if salida == "cerrar":
        return ChatResponse(estado=s["estado"], traza=traza,
                            mensaje="Entendido. Si luego necesitas un centro de salud, escribe «centro de salud cercano». "
                                    "Cuídate y vigila tus síntomas.")

    prefijo_extra = ""
    if salida == "corregir":
        correccion, s["correccion"] = s["correccion"] or {"tipo": "mostrar"}, None
        if correccion["tipo"] == "mostrar":
            if s["correcciones"] >= dialogo.MAX_CORRECCIONES:
                traza.append(f"Ya se corrigió {s['correcciones']} veces: no se ofrecen más correcciones")
                return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_confirmar(False),
                                    mensaje="Ya corregimos varias veces. Si algo no calza, empieza una «Nueva consulta»; "
                                            "si no, confirma. " + dialogo.texto_resumen(s["presentes"], s["ausentes"], resumen_grupo(s)))
            s["correccion_modo"] = "elegir"
            return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_quitar(s["presentes"]),
                                mensaje="¿Qué quieres corregir?")
        s["correcciones"] += 1
        s["confirmando"], s["correccion_modo"] = False, None
        if correccion["tipo"] == "agregar":
            s["aclaracion"] = "agregar"
            traza.append("Corrección: el usuario agregará otro síntoma")
            return ChatResponse(estado=s["estado"], traza=traza, opciones=dialogo.opciones_aclarar("agregar"),
                                mensaje=dialogo.MENSAJE_ACLARAR["agregar"])
        quitar_sintoma(s, correccion["id"], traza)
        prefijo_extra = f"Listo, quité «{nombre(correccion['id'])}». "
    if salida == "concluir":
        # confirmado: ahora sí se concluye con lo que hay (la transición (TRIAJE, confirmar) ya llevó a DERIVACION)
        s["confirmando"], s["correccion_modo"] = False, None
        hechos, pasos, iters = inferencia.inferir(inferencia.literales(s["presentes"], s["ausentes"]))
        traza += pasos
        traza.append(f"Inferencia final terminó en {iters} iteraciones")
        urg = inferencia.urgencia(hechos)
        if urg is None:
            traza.append("Sin conclusión: derivación segura por defecto (centro de salud)")
        return derivar(s, urg or "urgencia_media", traza, cuadros=inferencia.cuadros(hechos), hechos=hechos)

    # 3. Motor lógico + matriz como filtro previo
    s["confirmando"], s["correccion_modo"] = False, None
    s["turnos"] += 1
    hechos, pasos, iters = inferencia.inferir(inferencia.literales(s["presentes"], s["ausentes"]))
    traza.append(f"Matriz síntoma-cuadro (candidatos): {relaciones.candidatos(s['presentes'])}")
    traza += pasos
    traza.append(f"Inferencia terminó en {iters} iteraciones")
    urg = inferencia.urgencia(hechos)

    # 4. Árbol: siguiente pregunta, o concluir
    prox = arbol.siguiente_pregunta(s["presentes"], ausentes_arbol(s))
    if urg == "urgencia_alta":                        # alarma: se deriva de inmediato, sin pedir confirmación
        paso(s, "conclusion", traza, "urgencia alta: no se pide confirmación")
        return derivar(s, urg, traza, cuadros=inferencia.cuadros(hechos), hechos=hechos)
    if prox is None or s["turnos"] >= MAX_TURNOS:     # fin del interrogatorio: antes de concluir, se confirma
        return pedir_confirmacion(s, traza, prefijo_extra + ("Perdona, no te entendí. " if salida == "repetir" else ""))

    s["pendiente"] = prox
    traza.append(f"Árbol: siguiente pregunta → {prox}")
    prefijo = prefijo_extra + ("Perdona, no te entendí. " if salida == "repetir" else "")
    texto_pregunta, opciones = dialogo.pregunta_y_opciones(prox)
    return ChatResponse(estado=s["estado"], mensaje=prefijo + texto_pregunta, traza=traza, opciones=opciones)


def resumen_grupo(s: dict) -> str | None:
    return edad.etiqueta(s["grupo"]) if s["grupo"] else None


def pedir_confirmacion(s: dict, traza: list[str], prefijo: str = "") -> ChatResponse:
    """«Entendí que tienes… ¿Es correcto?»: se muestra antes de concluir para que el usuario pueda corregir."""
    s["confirmando"], s["pendiente"], s["correccion_modo"] = True, None, None
    texto = dialogo.texto_resumen(s["presentes"], s["ausentes"], resumen_grupo(s))
    traza.append("Fin del interrogatorio: se pide confirmar el resumen antes de concluir")
    puede = s["correcciones"] < dialogo.MAX_CORRECCIONES
    return ChatResponse(estado=s["estado"], mensaje=prefijo + texto, traza=traza, opciones=dialogo.opciones_confirmar(puede))


def quitar_sintoma(s: dict, id_: str, traza: list[str]) -> None:
    """El usuario dice que NO tiene ese síntoma: pasa a ausente. Si disparaba un seguimiento, este y sus efectos se anulan."""
    s["presentes"].discard(id_)
    s["ausentes"].add(id_)
    for sg in cargar("arbol").get("seguimientos", []):
        if sg["si"] == id_:
            s["respondidas"].discard(sg["pregunta"])
            for op in preguntas.opciones_de(sg["pregunta"]):
                for lit in op.get("efecto", {}).get("presentes", []) + op.get("efecto", {}).get("ausentes", []):
                    s["presentes"].discard(lit)
                    s["ausentes"].discard(lit)
    traza.append(f"Corrección: quito «{nombre(id_)}» (pasa a ausente) y vuelvo a razonar")


def iniciar_centro(s: dict, anterior: str, traza: list[str]) -> None:
    """Empieza la consulta de un establecimiento. Si no hay triaje se usa el nivel de centro de salud."""
    nivel = s["nivel"] or "urgencia_media"
    s["centro"] = {"nivel": nivel}
    traza.append(f"Consulta de establecimiento: nivel {nivel}" + ("" if s["nivel"] else " (aún no hay triaje: centro de salud)"))
    if anterior == "TRIAJE":
        s["retorno"] = True
        traza.append("Interrupción del triaje: se guarda el estado TRIAJE para volver al terminar")


def texto_pedir_ubicacion(s: dict) -> str:
    emergencia = (s["centro"] or {}).get("nivel") == "urgencia_alta"
    que = "la emergencia más cercana" if emergencia else "el centro de salud más cercano"
    return f"Comparte tu ubicación para indicarte {que}. {PRIVACIDAD_UBICACION}"


def derivar(s, urg, traza, cuadros=None, motivo="", hechos=None) -> ChatResponse:
    """Muestra la conclusión y encadena el siguiente paso según la urgencia:
    alta → ubicación (sin preguntar el seguro, Ley 27604); media → seguro; baja → ofrecer un centro."""
    nivel = niveles()[urg]   # data/niveles.json: acción, momento y categorías de establecimiento
    traza.append(f"Nivel de urgencia: {urg} (cuándo: {nivel['cuando']})")
    s["nivel"], s["retorno"], s["pendiente"] = urg, False, None
    s["confirmando"], s["correccion_modo"], s["correccion"], s["aclaracion"] = False, None, None, None   # el interrogatorio terminó
    cuadros = cuadros or []
    hechos = hechos or set()
    if cuadros:
        traza.append("Cuadros: " + ", ".join(fichas.etiqueta(c, hechos) for c in cuadros))
    resultado = Resultado(urgencia=urg, **fichas.datos_resultado(cuadros, hechos))

    siguiente, opciones = "", []
    if nivel.get("requiere_emergencia_24h"):
        paso(s, "seguro", traza, "emergencia: no se pregunta el seguro, Ley 27604")
        s["centro"] = {"nivel": urg}
        siguiente, opciones = f"{LEY_EMERGENCIAS}\n{texto_pedir_ubicacion(s)}", opciones_ubicacion()
    elif nivel.get("ruta_opcional"):
        s["oferta"] = True
        siguiente, opciones = "¿Quieres que te indique un centro de salud cercano por si lo necesitas?", opciones_si_no()
    else:
        s["centro"] = {"nivel": urg}
        if s["seguro"]:
            paso(s, "seguro", traza, f"seguro ya conocido: {s['seguro']}")
            siguiente, opciones = texto_pedir_ubicacion(s), opciones_ubicacion()
        else:
            paso(s, "buscar_centro", traza)
            siguiente, opciones = "Para indicarte el centro de salud más cercano, ¿qué seguro tienes?", opciones_seguro()

    # El SAMU 106 no se repite: ya está en la acción de urgencia alta.
    aviso = "Esto es orientación, no un diagnóstico." if urg == "urgencia_alta" else AVISO
    principal = " ".join(x for x in [motivo, fichas.frase_cuadros(cuadros, hechos), nivel["accion"]] if x)
    mensaje = "\n".join(x for x in [principal, siguiente, aviso] if x)
    return ChatResponse(estado=s["estado"], mensaje=mensaje, urgencia=urg, cuadros=cuadros, traza=traza,
                        opciones=opciones, resultado=resultado)


def mostrar_ruta(req: ChatRequest, s: dict, traza: list[str]) -> ChatResponse:
    """Calcula la ruta con la ubicación de ESTA petición (no se guarda) y devuelve el establecimiento."""
    nivel = (s["centro"] or {}).get("nivel") or s["nivel"] or "urgencia_media"
    sin_coordenadas = req.ubicacion_denegada or req.lat is None
    plan = ruteo.planificar(nivel, None if sin_coordenadas else req.lat, None if sin_coordenadas else req.lng, s["seguro"])
    traza += plan["traza"]
    ruta, fuera = plan["ruta"], plan["fuera_de_zona"]
    emergencia = niveles()[nivel].get("requiere_emergencia_24h")
    que = "Emergencia más cercana" if emergencia else "Centro de salud más cercano"

    partes: list[str] = []
    resultado = Resultado(urgencia=nivel, nota_seguro=plan["nota"])
    if ruta:
        detalle = ", ".join(x for x in (ruta["direccion"], f"tel. {ruta['telefono']}" if ruta["telefono"] else None) if x)
        partes.append(f"{que}: {ruta['destino']}, a unos {ruta['minutos']} min." + (f" {detalle}." if detalle else ""))
        resultado.establecimiento = EstablecimientoResultado(
            nombre=ruta["destino"], direccion=ruta["direccion"], telefono=ruta["telefono"], minutos=ruta["minutos"])
        if emergencia:
            partes.append("Si no puedes llegar, llama al SAMU 106.")
        opciones: list[Opcion] = []
    else:
        partes.append(("Estás fuera de la zona cubierta. " if fuera else "") + NO_RUTA)
        partes.append(texto_lista(plan["establecimientos"]))
        opciones = opciones_ubicacion(reintento=True)
    if plan["explicacion"]:
        partes.append(plan["explicacion"])
    if emergencia:
        partes.append(LEY_EMERGENCIAS)

    # Si el centro se pidió en mitad del triaje, se vuelve al triaje donde se quedó.
    if s["retorno"]:
        s["estado"], s["retorno"] = "TRIAJE", False
        traza.append("Fin de la consulta del centro: se restaura el estado TRIAJE (el triaje seguía en curso)")
    if s["estado"] == "TRIAJE" and s["pendiente"]:
        texto_pregunta, opciones_pregunta = dialogo.pregunta_y_opciones(s["pendiente"])
        partes.append("Volvamos al triaje: " + texto_pregunta)
        opciones = opciones + opciones_pregunta

    return ChatResponse(estado=s["estado"], mensaje="\n".join(p for p in partes if p), urgencia=nivel, traza=traza,
                        ruta=ruta, fuera_de_zona=fuera, establecimientos=plan["establecimientos"] if not ruta else [],
                        opciones=opciones, resultado=resultado)


def texto_lista(lista: list[dict]) -> str:
    """Recomendación sin ruta: los establecimientos adecuados."""
    if not lista:
        return ""
    lineas = []
    for f in lista:
        extra = ", ".join(x for x in (f["direccion"], f"tel. {f['telefono']}" if f["telefono"] else None) if x)
        lineas.append(f"• {f['nombre']}" + (f" ({extra})" if extra else ""))
    return "Establecimientos adecuados:\n" + "\n".join(lineas)
