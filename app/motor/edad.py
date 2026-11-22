"""Grupo de edad del paciente: una PARTICIÓN de todas las edades.

Los grupos de data/grupos_edad.json son intervalos de meses [desde, hasta) que no se traslapan y cubren desde
0 hasta el infinito, así que toda edad cae en UN grupo y solo uno. Eso reemplaza las tres preguntas sí/no
(menor de 6 meses, menor de 5 años, 60 años o más), que podían contradecirse entre sí.

El grupo se puede conocer de tres maneras (todas deterministas, sin LLM):
  1. el usuario toca una de las opciones de «¿Para quién es la consulta?»;
  2. el texto trae la edad ("mi hijo de 3 años", "tengo 70 años", "8 meses");
  3. el texto trae una frase que lo define ("adulto mayor", "recién nacido").
"""
import re

from app.datos import grupos_edad, literales_edad
from app.motor.extractor_keywords import normalizar

# "3 años", "70 anos", "8 meses". No cuenta si lo precede "hace" ("hace 3 años tuve…") ni "de embarazo" ("5 meses de embarazo").
PATRON_EDAD = re.compile(r"(?<!hace )\b(\d{1,3})\s*(anos?|meses|mes)\b(?!\s*de\s*(?:embarazo|gestacion))")
MAXIMO_ANOS = 120


def grupo_de_meses(meses: int) -> str:
    """El grupo que contiene esa edad. La partición garantiza que existe exactamente uno."""
    for gid, g in grupos_edad().items():
        if g["desde_meses"] <= meses and (g["hasta_meses"] is None or meses < g["hasta_meses"]):
            return gid
    raise ValueError(f"la edad {meses} meses no cae en ningún grupo: los grupos no son una partición")


def edad_en_meses(texto: str) -> int | None:
    """Edad que menciona el texto, en meses, o None."""
    m = PATRON_EDAD.search(normalizar(texto))
    if not m:
        return None
    n = int(m.group(1))
    if m.group(2).startswith("ano"):
        return n * 12 if n <= MAXIMO_ANOS else None
    return n


def reconocer(texto: str) -> tuple[str | None, str]:
    """(grupo, motivo) que se puede deducir del texto, o (None, '')."""
    normal = normalizar(texto).strip()
    for gid, g in grupos_edad().items():                       # 1. el botón que tocó (su etiqueta exacta)
        if normalizar(g["etiqueta"]).strip() == normal:
            return gid, "opción elegida"
    meses = edad_en_meses(texto)                                # 2. la edad en números
    if meses is not None:
        anos = f"{meses // 12} años" if meses >= 24 else f"{meses} meses"
        return grupo_de_meses(meses), f"edad detectada en el texto: {anos}"
    tokens = normal.split()                                     # 3. frases que definen el grupo (la más larga primero)
    frases = sorted(((c.split(), gid) for gid, g in grupos_edad().items() for c in g["claves"]), key=lambda f: -len(f[0]))
    for frase, gid in frases:
        n = len(frase)
        if any(tokens[i:i + n] == frase for i in range(len(tokens) - n + 1)):
            return gid, f"frase «{' '.join(frase)}»"
    return None, ""


def literales(gid: str) -> set[str]:
    return set(grupos_edad()[gid]["literales"])


def no_aplica(gid: str) -> set[str]:
    return set(grupos_edad()[gid]["no_aplica"])


def etiqueta(gid: str) -> str:
    return grupos_edad()[gid]["etiqueta"]


def ausentes_de_edad(gid: str) -> set[str]:
    """Los literales de edad que NO corresponden al grupo (para el razonamiento: es ese grupo y ningún otro)."""
    return literales_edad() - literales(gid)
