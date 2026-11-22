"""Carga única de los JSON de /data (datos estáticos y versionados)."""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache
def cargar(nombre: str) -> dict:
    with open(DATA / f"{nombre}.json", encoding="utf-8") as f:
        return json.load(f)


def sintomas() -> dict:
    return cargar("sintomas")["sintomas"]


def factores() -> dict:
    """Factores de riesgo (menor de 5 años, embarazo...): suben la urgencia."""
    return cargar("factores_riesgo")["factores"]


def cuadros() -> dict:
    """Fichas de los cuadros: nombre, CIE-10, cuidados y signos para volver."""
    return cargar("cuadros")["cuadros"]


def niveles() -> dict:
    """Del nivel de urgencia a la acción y a las categorías de establecimiento."""
    return cargar("niveles")["niveles"]


def seguros() -> dict:
    """Seguros de salud y las instituciones cuyos establecimientos acepta cada uno (data/seguros.json)."""
    return cargar("seguros")["seguros"]


def zona() -> dict:
    """Zona de cobertura: centro, radio y umbral de fuera de zona (data/zona.json)."""
    return cargar("zona")


def ids_sintomas() -> set[str]:
    return set(sintomas())


def ids_factores() -> set[str]:
    return set(factores())


def lexico() -> dict:
    """Lenguaje del chat: negadores, cortes, dudas, frases de 'incompleto'... (data/lexico.json)."""
    return cargar("lexico")


def grupos_edad() -> dict:
    """Partición de las edades en grupos (data/grupos_edad.json)."""
    return cargar("grupos_edad")["grupos"]


def literales_edad() -> set[str]:
    """Literales de edad que usan las reglas de riesgo (menor_6_meses, menor_5, mayor_60...)."""
    return {l for g in grupos_edad().values() for l in g["literales"]}


def preguntas_especiales() -> dict:
    """Preguntas del árbol que no son sí/no (data/preguntas.json)."""
    return cargar("preguntas")["preguntas"]


def ids_extraibles() -> set[str]:
    """Lista cerrada que puede devolver un extractor: síntomas y factores de riesgo.
    La edad NO: se pregunta como un grupo (una partición), no como tres preguntas sí/no."""
    return ids_sintomas() | (ids_factores() - literales_edad())


def nombre(id_: str) -> str:
    """Nombre legible (data/nombres.json) para mostrar al usuario; nunca el id."""
    return cargar("nombres")["nombres"].get(id_) or id_.replace("_", " ")


def ids_alarma() -> set[str]:
    return {s for s, d in sintomas().items() if d["alarma"]}


def pregunta(id_: str) -> str:
    """Pregunta cerrada (sí / no) de un síntoma o de un factor de riesgo."""
    if id_ in preguntas_especiales():
        return preguntas_especiales()[id_]["pregunta"]
    return (sintomas().get(id_) or factores()[id_])["pregunta"]
