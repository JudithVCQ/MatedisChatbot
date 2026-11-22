"""Plan B: extractor por palabras clave con un autómata finito de negación.

Autómata (Q = {AFIRMA, NIEGA}):
    AFIRMA --negador--> NIEGA        ("no", "sin", "ni", ...)
    NIEGA  --corte----> AFIRMA       ("pero", "y", "aunque", ...)
    NIEGA  --"ni"-----> NIEGA        (la negación continúa: "no tengo fiebre ni tos")
    cualquier otro token: se queda en el mismo estado
Un síntoma reconocido en AFIRMA va a 'presentes'; en NIEGA, a 'ausentes'.
"""
import re
import unicodedata
from functools import lru_cache

from app.datos import factores, ids_alarma, lexico, literales_edad, sintomas
from app.motor import levenshtein
from app.schemas import Extraccion

VENTANA_DUDA = 4  # tokens alrededor de un término de alarma para detectar duda


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zñ0-9 ]+", " ", texto)


def _frases() -> list[tuple[list[str], str]]:
    """Todas las claves (síntomas y factores de riesgo) como listas de tokens, de la más larga a la más corta."""
    # La edad no se extrae aquí: se reconoce como grupo (app/motor/edad.py).
    extraibles = {**sintomas(), **{k: v for k, v in factores().items() if k not in literales_edad()}}
    frases = [(clave.split(), sid) for sid, d in extraibles.items() for clave in d["claves"]]
    return sorted(frases, key=lambda f: -len(f[0]))


SOLO_EXACTAS = {"si", "sip", "claro", "obvio", "aja", "correcto", "nop"}   # respuestas sí/no: tampoco se corrigen


@lru_cache
def vocabulario() -> dict[str, set[str]]:
    """Palabras que aparecen en las claves de síntomas y factores → los ids a los que apuntan."""
    vocab: dict[str, set[str]] = {}
    for frase, sid in _frases():
        for palabra in frase:
            vocab.setdefault(palabra, set()).add(sid)
    return vocab


@lru_cache
def protegidas() -> frozenset[str]:
    """Palabras que NUNCA se corrigen ni son destino de una corrección: negadores, cortes, dudas y palabras comunes.
    Los negadores y cortes mueven el autómata (AFIRMA/NIEGA): un error de ortografía no puede cambiar su significado."""
    cfg = lexico()
    dudas = {t for d in cfg["dudas"] for t in d.split()}
    return frozenset(cfg["negadores"]) | frozenset(cfg["cortes"]) | dudas | frozenset(cfg["comunes"]) | SOLO_EXACTAS


@lru_cache
def destinos_de_correccion() -> dict[str, set[str]]:
    """Palabras HACIA las que se puede corregir: el vocabulario sin las protegidas (nunca se corrige hacia 'no' ni 'hacer')."""
    seguras = protegidas()
    return {p: ids for p, ids in vocabulario().items() if p not in seguras}


def corregir_ortografia(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Corrige con Levenshtein las palabras que no coinciden con ninguna clave. Devuelve (tokens, líneas de traza)."""
    vocab, seguras, destinos = vocabulario(), protegidas(), destinos_de_correccion()
    resultado, traza = [], []
    for tok in tokens:
        if tok in vocab or tok in seguras or not tok.isalpha():
            resultado.append(tok)
            continue
        hallada = levenshtein.corregir(tok, destinos)
        if hallada is None:
            resultado.append(tok)
            continue
        palabra, d = hallada
        resultado.append(palabra)
        traza.append(f"Corregí '{tok}' → '{palabra}' (distancia {d})")
    return resultado, traza


def extraer(texto: str) -> Extraccion:
    cfg = lexico()
    negadores, cortes = set(cfg["negadores"]), set(cfg["cortes"])
    dudas = [d.split() for d in cfg["dudas"]]
    tokens, correcciones = corregir_ortografia(normalizar(texto).split())
    frases = _frases()

    estado = "AFIRMA"
    presentes, ausentes = set(), set()
    posiciones_alarma, posiciones_duda = [], []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Las claves que EMPIEZAN con un negador ("no puedo respirar", "no huelo") ya traen su significado: son un
        # síntoma presente. Se emparejan antes de tratar el "no" como negador (si no, nunca se detectarían).
        propia = next(((f, sid) for f, sid in frases if f[0] in negadores and tokens[i:i + len(f)] == f), None)
        if propia:
            presentes.add(propia[1])
            if propia[1] in ids_alarma():
                posiciones_alarma.append(i)
            i += len(propia[0])
            continue
        # transiciones del autómata
        if tok in negadores:
            estado = "NIEGA"
            i += 1
            continue
        if tok in cortes and estado == "NIEGA":
            estado = "AFIRMA"
            i += 1
            continue
        # palabras de duda
        for d in dudas:
            if tokens[i:i + len(d)] == d:
                posiciones_duda.append(i)
        # reconocimiento de síntomas (coincidencia más larga primero)
        for frase, sid in frases:
            if tokens[i:i + len(frase)] == frase:
                (ausentes if estado == "NIEGA" else presentes).add(sid)
                if sid in ids_alarma() and estado == "AFIRMA":
                    posiciones_alarma.append(i)
                i += len(frase) - 1
                break
        i += 1

    ausentes -= presentes  # si se afirma en algún punto, gana "presente" (fallar hacia la seguridad)
    incierta = any(abs(a - d) <= VENTANA_DUDA for a in posiciones_alarma for d in posiciones_duda)
    return Extraccion(presentes=presentes, ausentes=ausentes, alarma_incierta=incierta, correcciones=correcciones)


def es_si(texto: str) -> bool | None:
    """Respuesta a una pregunta cerrada: True, False o None si no es sí/no."""
    t = normalizar(texto).split()
    if not t:
        return None
    if t[0] in {"si", "sip", "claro", "obvio", "aja", "correcto"}:
        return True
    if t[0] in {"no", "nop", "nada", "tampoco"}:
        return False
    return None
