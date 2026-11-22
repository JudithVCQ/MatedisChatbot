"""Árbol binario de decisión, recorrido recursivamente.

Orden de las preguntas: 1) alarma, 2) factores de riesgo, 3) diagnóstico.
En data/arbol.json las listas 'alarma' y 'factores' son cadenas de nodos; al cargar se
arma el árbol completo. Los nodos de una cadena de factores comparten el mismo subárbol
en memoria (si = no), por eso las funciones que recorren todo el árbol no repiten trabajo.
"""
from functools import lru_cache

from app.datos import cargar

HOJA = {"hoja": True}


@lru_cache
def raiz() -> dict:
    datos = cargar("arbol")
    nodo = datos["raiz"]
    for factor in reversed(datos["factores"]):      # preguntar el factor y seguir igual
        nodo = {"sintoma": factor, "si": nodo, "no": nodo}
    for alarma in reversed(datos["alarma"]):        # alarma: "sí" termina, "no" sigue
        nodo = {"sintoma": alarma, "si": HOJA, "no": nodo}
    return nodo


def siguiente(nodo: dict, presentes: set[str], ausentes: set[str]) -> str | None:
    """Devuelve el próximo síntoma o factor a preguntar, o None si se llegó a una hoja.

    Recursión: si el síntoma del nodo ya se conoce, se baja por la rama que
    corresponde sin preguntar; si no se conoce, ese es el que se pregunta.
    """
    if nodo.get("hoja"):
        return None
    s = nodo["sintoma"]
    if s in presentes:
        return siguiente(nodo["si"], presentes, ausentes)
    if s in ausentes:
        return siguiente(nodo["no"], presentes, ausentes)
    return s


def preorden(nodo: dict, nivel: int = 0, listados: set[int] | None = None) -> list[str]:
    """Recorrido en preorden (raíz, si, no): sirve para listar el árbol en la defensa.

    Un subárbol compartido se lista una sola vez; las demás veces se indica con '↻'.
    """
    listados = set() if listados is None else listados
    sangria = "  " * nivel
    if nodo.get("hoja"):
        return [sangria + "• fin"]
    if id(nodo) in listados:
        return [sangria + nodo["sintoma"] + "?  ↻ (subárbol ya listado)"]
    listados.add(id(nodo))
    return ([sangria + nodo["sintoma"] + "?"]
            + preorden(nodo["si"], nivel + 1, listados) + preorden(nodo["no"], nivel + 1, listados))


def altura(nodo: dict) -> int:
    """Máximo de preguntas posibles (útil para justificar el límite de turnos)."""
    if nodo.get("hoja"):
        return 0
    a = altura(nodo["si"])
    b = a if nodo["no"] is nodo["si"] else altura(nodo["no"])
    return 1 + max(a, b)


def preguntados(nodo: dict | None = None, vistos: set[int] | None = None) -> set[str]:
    """Todos los síntomas y factores por los que el árbol puede preguntar."""
    if nodo is None:                                   # desde la raíz: el árbol y las preguntas de seguimiento
        return preguntados(raiz(), set()) | {sg["pregunta"] for sg in cargar("arbol").get("seguimientos", [])}
    vistos = set() if vistos is None else vistos
    if nodo.get("hoja") or id(nodo) in vistos:
        return set()
    vistos.add(id(nodo))
    return {nodo["sintoma"]} | preguntados(nodo["si"], vistos) | preguntados(nodo["no"], vistos)


def prefijo() -> set[str]:
    """Las preguntas de la alarma y de los factores: siempre van antes que los seguimientos."""
    datos = cargar("arbol")
    return set(datos["alarma"]) | set(datos["factores"])


def seguimiento_pendiente(presentes: set[str], resueltas: set[str]) -> str | None:
    """Pregunta de seguimiento que corresponde ahora: el síntoma disparador está presente y aún no se contestó."""
    for sg in cargar("arbol").get("seguimientos", []):
        if sg["si"] in presentes and sg["pregunta"] not in resueltas:
            return sg["pregunta"]
    return None


def siguiente_pregunta(presentes: set[str], ausentes: set[str]) -> str | None:
    """La próxima pregunta: el árbol, con los seguimientos intercalados tras la alarma y los factores.
    `ausentes` incluye lo negado, lo que no aplica y las preguntas especiales ya contestadas."""
    q = siguiente(raiz(), presentes, ausentes)
    if q in prefijo():
        return q                                       # primero la alarma y los factores
    return seguimiento_pendiente(presentes, ausentes) or q


def altura_total() -> int:
    """Máximo de preguntas posibles: la altura del árbol más un seguimiento por disparador (cota para MAX_TURNOS)."""
    return altura(raiz()) + len(cargar("arbol").get("seguimientos", []))
