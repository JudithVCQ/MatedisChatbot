"""Distancia de Levenshtein por programación dinámica (implementación propia) y corrección de palabras.

La distancia d(a, b) es el mínimo número de ediciones de UN carácter (insertar, borrar o sustituir) para convertir
la palabra a en la palabra b. Sea D[i][j] la distancia entre los primeros i caracteres de a y los primeros j de b:

    D[i][0] = i                        (borrar los i caracteres de a)
    D[0][j] = j                        (insertar los j caracteres de b)
    D[i][j] = min( D[i-1][j]   + 1,                    ← borrar a[i]
                   D[i][j-1]   + 1,                    ← insertar b[j]
                   D[i-1][j-1] + (a[i] ≠ b[j]) )       ← sustituir (cuesta 0 si ya son iguales)

La respuesta es D[len(a)][len(b)]. Cada celda depende solo de sus tres vecinas (izquierda, arriba y diagonal),
así que se llena fila por fila: basta recordar la fila anterior, lo que cuesta O(|a|·|b|) tiempo y O(|b|) memoria.
Es una métrica: d(a,a)=0, d(a,b)=d(b,a) y d(a,c) ≤ d(a,b)+d(b,c). Un intercambio de dos letras vecinas
("fiebre" → "feibre") cuenta como 2 ediciones.

Corregir una palabra = buscar, entre las palabras conocidas, la más cercana, pero SOLO si está lo bastante cerca
(umbral según el largo) para no inventar síntomas.
"""

UMBRAL_CORTO, UMBRAL_MEDIO, UMBRAL_LARGO = 0, 1, 2


def distancia(a: str, b: str) -> int:
    """Distancia de Levenshtein entre a y b (programación dinámica, dos filas)."""
    if a == b:
        return 0
    anterior = list(range(len(b) + 1))                 # D[0][j] = j
    for i, ca in enumerate(a, start=1):
        actual = [i]                                   # D[i][0] = i
        for j, cb in enumerate(b, start=1):
            actual.append(min(anterior[j] + 1,                    # borrar
                              actual[j - 1] + 1,                  # insertar
                              anterior[j - 1] + (ca != cb)))      # sustituir
        anterior = actual
    return anterior[-1]


def umbral(largo: int) -> int:
    """Distancia máxima tolerada según el largo de la palabra:
    menos de 5 letras → 0 (solo exacta: evita "los" → "tos"); 5 a 7 letras → 1; 8 o más → 2."""
    if largo < 5:
        return UMBRAL_CORTO
    return UMBRAL_MEDIO if largo <= 7 else UMBRAL_LARGO


def corregir(palabra: str, vocabulario: dict[str, set[str]]) -> tuple[str, int] | None:
    """La palabra conocida más cercana a `palabra`, o None si no hay una lo bastante cerca.

    `vocabulario` asigna a cada palabra conocida el conjunto de significados a los que apunta (p. ej. los síntomas).
    El umbral depende del largo de la MÁS LARGA de las dos (así "peho" 4 letras → "pecho" 5 letras se corrige con
    distancia 1, pero "los" → "tos" nunca). Si dos palabras conocidas distintas empatan en cercanía y apuntan a
    significados distintos, es ambiguo y NO se corrige: es mejor preguntar que adivinar."""
    mejor: list[str] = []
    mejor_d = 10 ** 6
    for conocida in vocabulario:
        if abs(len(conocida) - len(palabra)) > UMBRAL_LARGO:
            continue
        d = distancia(palabra, conocida)
        if d == 0 or d > umbral(max(len(palabra), len(conocida))):
            continue
        if d < mejor_d:
            mejor, mejor_d = [conocida], d
        elif d == mejor_d:
            mejor.append(conocida)
    if not mejor:
        return None
    significados = {frozenset(vocabulario[c]) for c in mejor}
    if len(mejor) > 1 and len(significados) > 1:
        return None                                    # empate entre significados distintos: ambiguo
    return sorted(mejor)[0], mejor_d
