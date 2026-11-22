"""Fichas de los cuadros (data/cuadros.json): nombre, CIE-10, cuidados y signos para volver.

Nada de esto lo decide el LLM: el texto viene de los datos y solo se ordena aquí.
"""
from app.datos import cuadros, ids_alarma

PREFIJO_VARIANTE = "cie10_con_"
VARIANTE_ALARMA = "cie10_con_alarma"


def cie10(cuadro: str, hechos: set[str]) -> str | None:
    """Código CIE-10 del cuadro. Las variantes salen de los datos:
    'cie10_con_<síntoma>' si ese síntoma está presente; 'cie10_con_alarma' si hay algún signo de alarma."""
    c = cuadros().get(cuadro)
    if c is None:
        return None
    for clave, codigo in c.items():
        if clave.startswith(PREFIJO_VARIANTE) and clave != VARIANTE_ALARMA:
            if clave[len(PREFIJO_VARIANTE):] in hechos:
                return codigo
    if VARIANTE_ALARMA in c and hechos & ids_alarma():
        return c[VARIANTE_ALARMA]
    return c["cie10"]


def _en_frase(nombre: str) -> str:
    """'Dengue' → 'dengue' para usarlo dentro de una frase; 'COVID-19' se deja igual."""
    return nombre if nombre[:2].isupper() else nombre[:1].lower() + nombre[1:]


def nombre_en_frase(cuadro: str) -> str:
    """Nombre del cuadro para usarlo dentro de una frase («dengue», «COVID-19»)."""
    c = cuadros().get(cuadro)
    return _en_frase(c["nombre"]) if c else cuadro


def etiqueta(cuadro: str, hechos: set[str]) -> str:
    """Texto corto para el usuario y la traza, p. ej. 'dengue (CIE-10 A97.0)'."""
    c = cuadros().get(cuadro)
    codigo = cie10(cuadro, hechos)
    nombre = _en_frase(c["nombre"]) if c else cuadro
    return f"{nombre} (CIE-10 {codigo})" if codigo else nombre


def frase_cuadros(ids: list[str], hechos: set[str]) -> str:
    """'Posible dengue (CIE-10 A97.0).' o 'Posibles cuadros: a (…), b (…).'; vacío si no hay cuadros."""
    etiquetas = [etiqueta(c, hechos) for c in ids]
    if len(etiquetas) == 1:
        return f"Posible {etiquetas[0]}."
    if etiquetas:
        return f"Posibles cuadros: {', '.join(etiquetas)}."
    return ""


def datos_resultado(ids: list[str], hechos: set[str]) -> dict:
    """Cuadro, CIE-10, cuidados y signos para volver, ya estructurados (con varios cuadros se unen sin repetir)."""
    nombres, codigos, cuidados, volver = [], [], [], []
    for cuadro in ids:
        c = cuadros().get(cuadro)
        if c is None:
            continue
        nombres.append(c["nombre"])
        codigo = cie10(cuadro, hechos)
        if codigo:
            codigos.append(codigo)
        cuidados += [x for x in c.get("cuidados", []) if x not in cuidados]
        volver += [x for x in c.get("volver_si", []) if x not in volver]
    return {"cuadro": " / ".join(nombres) or None, "cie10": ", ".join(codigos) or None,
            "cuidados": cuidados, "volver_si": volver}


def texto_cuidados(ids: list[str]) -> str:
    """Cuidados y signos para volver de cada cuadro, en viñetas (una línea por elemento)."""
    lineas: list[str] = []
    for cuadro in ids:
        c = cuadros().get(cuadro)
        if c is None:
            continue
        titulo = f"{_en_frase(c['nombre'])}: " if len(ids) > 1 else ""
        if c.get("cuidados"):
            lineas += [f"{titulo}Cuidados:"] + [f"• {x}" for x in c["cuidados"]]
        if c.get("volver_si"):
            lineas += [f"{titulo}Vuelve a consultar o acude a emergencias si:"] + [f"• {x}" for x in c["volver_si"]]
    return "\n".join(lineas)
