"""Textos y botones del diálogo (sin estado): preguntas, atajos y aclaraciones. Todo determinista, sin LLM."""
from app.datos import grupos_edad, ids_alarma, lexico, literales_edad, nombre, pregunta, preguntas_especiales
from app.motor import fichas, relaciones
from app.motor.extractor_keywords import normalizar
from app.schemas import Opcion

# Los botones envían su etiqueta como mensaje; el extractor la entiende porque contiene las claves del síntoma.
ATAJOS = ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Dolor de cabeza", "Otro síntoma"]
DONDE = ["Pecho", "Cabeza", "Garganta", "Barriga", "Cuerpo/músculos", "Detrás de los ojos", "Otro lugar"]   # Pecho primero: es alarma
QUE = ["Fiebre", "Tos", "Dolor de garganta", "Diarrea", "Vómitos", "Dolor de cabeza", "Cansancio", "Otro síntoma"]

AYUDA = "No estoy seguro de haber entendido. ¿Alguno de estos se parece a lo que sientes?"
SALUDO = "Hola. Cuéntame con tus palabras qué síntomas tienes, o elige uno de estos."
MENSAJE_ACLARAR = {
    "donde": "¿Dónde te duele?",
    "que": "¿Qué sientes?",
    "libre": "Cuéntame con tus palabras qué sientes.",
    "agregar": "¿Qué otro síntoma tienes? Elige uno o cuéntamelo con tus palabras.",
}


def _opciones(etiquetas: list[str]) -> list[Opcion]:
    return [Opcion(etiqueta=e, valor=e) for e in etiquetas]


def opciones_si_no() -> list[Opcion]:
    return [Opcion(etiqueta="Sí", valor="sí"), Opcion(etiqueta="No", valor="no")]


def opciones_atajos() -> list[Opcion]:
    return _opciones(ATAJOS)


def opciones_aclarar(tipo: str) -> list[Opcion]:
    return _opciones({"donde": DONDE, "que": QUE, "agregar": QUE}.get(tipo, []))


def pregunta_y_opciones(id_: str) -> tuple[str, list[Opcion]]:
    """Texto y botones de una pregunta del árbol. Sin '(sí / no)': los botones ya lo dicen."""
    especial = preguntas_especiales().get(id_)
    if especial and especial["tipo"] == "grupo":
        botones = _opciones([g["etiqueta"] for g in grupos_edad().values()])
    elif especial:
        botones = _opciones([o["etiqueta"] for o in especial["opciones"]])
    else:
        botones = opciones_si_no()
    return pregunta(id_), botones + [opcion_por_que()]


def _contiene(tokens: list[str], frase: list[str]) -> bool:
    n = len(frase)
    return any(tokens[i:i + n] == frase for i in range(len(tokens) - n + 1))


def tipo_incompleto(texto: str) -> str | None:
    """¿El mensaje dice que algo le pasa pero no QUÉ? 'donde' ("tengo dolor"), 'que' ("me siento mal") o None.
    Solo se usa cuando no se reconoció ningún síntoma."""
    lex = lexico()
    tokens = normalizar(texto).split()
    halladas = [f for f in lex["incompletos"] if _contiene(tokens, f.split())]
    if not halladas:
        return None
    return "que" if any(f in lex["incompletos_que"] for f in halladas) else "donde"


POR_QUE = "¿Por qué?"
SIN_PREGUNTA = "No hay una pregunta pendiente que explicar."


def opcion_por_que() -> Opcion:
    return Opcion(etiqueta=POR_QUE, valor=POR_QUE, accion="por_que")


def es_por_que(texto: str) -> bool:
    """«¿Por qué?», «¿Por qué me preguntas esto?», «¿para qué?»: frase corta que empieza con por qué / para qué."""
    tokens = normalizar(texto).split()
    return 0 < len(tokens) <= 8 and any(tokens[:len(f.split())] == f.split() for f in lexico()["por_que"])


def _unir(nombres: list[str]) -> str:
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def explicacion(id_: str, presentes: set[str]) -> tuple[str, list[str]]:
    """Por qué se hace esa pregunta, con relaciones.py: los cuadros candidatos actuales que tienen ese literal en sus
    reglas. Devuelve (texto, ids de los cuadros nombrados)."""
    cuadros = relaciones.cuadros_de_pregunta(id_, presentes)
    nombres = [fichas.nombre_en_frase(c) for c in cuadros]
    dicho = sorted({nombre(i) for i in presentes - literales_edad()})
    partes = []
    if id_ in ids_alarma():
        partes.append("Es una pregunta de seguridad: descarta un signo de alarma que necesita emergencias.")
    if nombres:
        verbo = "ayuda a distinguir entre" if len(nombres) > 1 else "ayuda a confirmar o descartar"
        intro = f"Con {_unir(dicho)}, esta" if dicho else "Esta"
        partes.append(f"{intro} respuesta {verbo} {_unir(nombres)}.")
    if relaciones.afecta_la_urgencia(id_) and id_ not in ids_alarma():
        partes.append("También puede subir qué tan urgente es tu caso.")
    return " ".join(partes) or "Sirve para decidir qué tan urgente es tu caso.", cuadros


def es_otro(texto: str) -> bool:
    """«Otro síntoma», «otro lugar»: quiere describirlo con sus palabras."""
    tokens = normalizar(texto).split()
    return any(_contiene(tokens, f.split()) for f in lexico()["otro"])


DESHACER = "Me equivoqué"
AVISO_DESHACER_ALARMA = "Si de verdad tienes ese síntoma, acude a emergencias o llama al SAMU 106."


def es_deshacer(texto: str) -> bool:
    """«Me equivoqué», «deshacer», «volver atrás»."""
    tokens = normalizar(texto).split()
    return any(_contiene(tokens, f.split()) for f in lexico()["deshacer"])


def opcion_deshacer() -> Opcion:
    return Opcion(etiqueta=DESHACER, valor=DESHACER, accion="deshacer")


# ---------- confirmación antes de concluir ----------
CONFIRMAR = "Sí, es correcto"
CORREGIR = "Corregir"
AGREGAR = "Agregar otro síntoma"
MAX_CORRECCIONES = 3        # tope: así el diálogo de corrección siempre termina


def corregibles(presentes: set[str]) -> list[str]:
    """Lo que el usuario puede quitar: síntomas y factores presentes (no la edad, que se fija por grupo), por nombre."""
    return sorted(presentes - literales_edad(), key=nombre)


def texto_quitar(id_: str) -> str:
    return f"Quitar {nombre(id_)}"


def _lista(ids) -> str:
    return ", ".join(sorted({nombre(i) for i in ids}))


def texto_resumen(presentes: set[str], ausentes: set[str], grupo: str | None) -> str:
    """«Entendí que tienes: … y que NO tienes: … ¿Es correcto?» con nombres legibles, nunca ids."""
    tiene = presentes - literales_edad()
    no_tiene = ausentes - literales_edad()
    partes = ["Entendí que tienes: " + _lista(tiene) if tiene else "Entendí que no mencionaste síntomas"]
    if no_tiene:
        partes.append("y que NO tienes: " + _lista(no_tiene))
    texto = ", ".join(partes) + "."
    if grupo:
        texto += f" La consulta es para: {grupo[0].lower() + grupo[1:]}."
    return texto + " ¿Es correcto?"


def opciones_confirmar(puede_corregir: bool = True) -> list[Opcion]:
    return _opciones([CONFIRMAR, CORREGIR] if puede_corregir else [CONFIRMAR])


def opciones_quitar(presentes: set[str]) -> list[Opcion]:
    return _opciones([texto_quitar(i) for i in corregibles(presentes)] + [AGREGAR])
