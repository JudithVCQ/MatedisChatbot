"""Medidas que trae el texto libre: temperatura y número de días. Solo patrones (sin LLM).

  temperatura: "39 de fiebre", "38.5 grados", "fiebre de 39", "temperatura 38,2", "39°".  ≥ 38 °C cuenta como fiebre.
  días:        "hace 4 días", "fiebre de 5 días", "4 días con fiebre", "más de 3 días". Solo NÚMEROS de días
               ("desde el lunes" o "hace una semana" no se interpretan).
"""
import re

from app.motor.extractor_keywords import normalizar

UMBRAL_FIEBRE_C = 38.0
RANGO_TEMPERATURA_C = (34.0, 43.0)       # fuera de esto el número no es una temperatura corporal
NUM = r"(\d{2}(?:[.,]\d)?)"
PATRONES_TEMPERATURA = [
    re.compile(NUM + r"\s*(?:grados|°\s*c?|º\s*c?|c\b)"),                     # 38.5 grados · 39° · 38 c
    re.compile(NUM + r"\s*de\s*(?:fiebre|temperatura)"),                       # 39 de fiebre
    re.compile(r"(?:fiebre|temperatura)\s*(?:de|:|a|en)?\s*" + NUM),           # fiebre de 39 · temperatura 38,2
]
PATRON_MAS_DE = re.compile(r"\bmas\s+de\s+(\d{1,3})\s*dias?\b")
PATRON_DIAS = re.compile(r"\b(\d{1,3})\s*dias?\b")
MAXIMO_DIAS = 365


def temperatura(texto: str) -> float | None:
    """La temperatura (°C) que menciona el texto, o None."""
    bajo = texto.lower()
    for patron in PATRONES_TEMPERATURA:
        for m in patron.finditer(bajo):
            valor = float(m.group(1).replace(",", "."))
            if RANGO_TEMPERATURA_C[0] <= valor <= RANGO_TEMPERATURA_C[1]:
                return valor
    return None


def es_fiebre(grados: float) -> bool:
    return grados >= UMBRAL_FIEBRE_C


def dias(texto: str) -> int | None:
    """El número de días que menciona el texto ("hace 4 días" → 4; "más de 3 días" → 4), o None."""
    normal = normalizar(texto)
    m = PATRON_MAS_DE.search(normal)
    if m:
        n = int(m.group(1)) + 1
    else:
        m = PATRON_DIAS.search(normal)
        if not m:
            return None
        n = int(m.group(1))
    return n if 0 <= n <= MAXIMO_DIAS else None
