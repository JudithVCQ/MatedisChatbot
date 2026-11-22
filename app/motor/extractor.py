"""Combina ambos extractores. El detector de alarma por palabras clave corre SIEMPRE.

alarma = alarma_LLM ∨ alarma_keywords
"""
from app.datos import ids_alarma
from app.motor import extractor_keywords, extractor_llm
from app.schemas import Extraccion


def extraer(texto: str) -> tuple[Extraccion, str]:
    kw = extractor_keywords.extraer(texto)
    llm = extractor_llm.extraer(texto)
    if llm is None:
        return kw, "palabras clave"

    alarma_kw = kw.presentes & ids_alarma()
    presentes = llm.presentes | alarma_kw            # la alarma de keywords nunca se pierde
    ausentes = llm.ausentes - presentes
    return (
        Extraccion(presentes=presentes, ausentes=ausentes,
                   alarma_incierta=llm.alarma_incierta or kw.alarma_incierta, correcciones=kw.correcciones),
        "LLM + detector de alarma",
    )


def hay_alarma(e: Extraccion) -> bool:
    return bool(e.presentes & ids_alarma()) or e.alarma_incierta
