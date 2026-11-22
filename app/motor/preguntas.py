"""Preguntas de varias opciones (data/preguntas.json): reconocer la respuesta y sus efectos sobre el razonamiento."""
from app.datos import preguntas_especiales
from app.motor.extractor_keywords import normalizar


def _contiene(tokens: list[str], frase: list[str]) -> bool:
    n = len(frase)
    return any(tokens[i:i + n] == frase for i in range(len(tokens) - n + 1))


def opciones_de(id_: str) -> list[dict]:
    return preguntas_especiales()[id_].get("opciones", [])


def opcion_por_dias(id_: str, dias: int) -> dict | None:
    """La opción cuyo rango de días contiene `dias` (solo las preguntas cuyas opciones tienen 'dias': [mín, máx])."""
    for op in opciones_de(id_):
        rango = op.get("dias")
        if rango and rango[0] <= dias and (rango[1] is None or dias <= rango[1]):
            return op
    return None


def reconocer_opcion(id_: str, texto: str, dias: int | None = None) -> dict | None:
    """Qué opción eligió el usuario. Orden: la etiqueta exacta del botón, luego frases clave y, al final, el número
    de días (así «más de 3 días» no se confunde con «1 a 3 días» aunque ambos traigan un 3)."""
    normal = normalizar(texto).strip()
    ops = opciones_de(id_)
    for op in ops:
        if normalizar(op["etiqueta"]).strip() == normal:
            return op
    tokens = normal.split()
    candidatas = sorted(((c.split(), op) for op in ops for c in op["claves"]), key=lambda x: -len(x[0]))
    for frase, op in candidatas:
        if _contiene(tokens, frase):
            return op
    if dias is not None:
        return opcion_por_dias(id_, dias)
    return None
