"""Seguro del usuario (data/seguros.json): reconocer su respuesta y detectar que pide un establecimiento.

El LLM no participa: todo se resuelve con palabras clave sobre texto normalizado, como el extractor.
"""
from app.datos import cargar, seguros
from app.motor.extractor_keywords import normalizar


def _contiene(tokens: list[str], frase: list[str]) -> bool:
    n = len(frase)
    return any(tokens[i:i + n] == frase for i in range(len(tokens) - n + 1))


def reconocer(texto: str) -> str | None:
    """Id del seguro mencionado, o None. Gana la frase más larga ('no tengo seguro' antes que 'no')."""
    tokens = normalizar(texto).split()
    mejor, mejor_largo = None, 0
    for sid, s in seguros().items():
        for clave in s["claves"]:
            frase = clave.split()
            if len(frase) > mejor_largo and _contiene(tokens, frase):
                mejor, mejor_largo = sid, len(frase)
    return mejor


def pide_centro(texto: str) -> bool:
    """¿El usuario pregunta dónde atenderse? ('¿dónde me atiendo?', 'hospital cerca', 'posta'...)"""
    tokens = normalizar(texto).split()
    return any(_contiene(tokens, frase.split()) for frase in cargar("seguros")["busqueda_centro"])


def etiqueta(sid: str) -> str:
    return seguros()[sid]["etiqueta"]


def nota(sid: str | None) -> str | None:
    return seguros()[sid]["nota"] if sid else None


def opciones() -> list[dict]:
    """Botones de la pregunta del seguro. 'valor' es lo que se envía y siempre se reconoce a sí mismo."""
    return [{"etiqueta": s["etiqueta"], "valor": s["etiqueta"]} for s in seguros().values()]
