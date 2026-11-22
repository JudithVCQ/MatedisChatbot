"""Relaciones como matrices booleanas y su composición.

M_SC: síntoma × cuadro   (1 si el síntoma aparece en alguna regla del cuadro)
M_CU: cuadro × urgencia  (1 si el cuadro implica esa urgencia)
M_SU = M_SC ⊙ M_CU       (producto booleano: OR de ANDs)

Uso: FILTRO PREVIO. La matriz propone cuadros candidatos; el motor lógico decide.

Además: seguro → institución → establecimiento (M_SE = M_SI ⊙ M_IE), para elegir el destino según el seguro.
"""
from app.datos import cargar, ids_sintomas, literales_edad, preguntas_especiales
from app.datos import cuadros as datos_cuadros
from app.datos import seguros as datos_seguros


def _cuadros_y_urgencias():
    reglas = cargar("reglas")["reglas"]
    niveles = cargar("reglas")["niveles_urgencia"]
    sintomas = sorted(ids_sintomas())
    cuadros = sorted({r["entonces"] for r in reglas
                      if r["entonces"] not in niveles and all(p.lstrip("~") in sintomas for p in r["si"])})
    return reglas, niveles, sintomas, cuadros


def matrices():
    reglas, niveles, sintomas, cuadros = _cuadros_y_urgencias()
    m_sc = [[0] * len(cuadros) for _ in sintomas]
    m_cu = [[0] * len(niveles) for _ in cuadros]
    for r in reglas:
        if r["entonces"] in cuadros:
            for p in r["si"]:
                if not p.startswith("~"):
                    m_sc[sintomas.index(p)][cuadros.index(r["entonces"])] = 1
        if r["entonces"] in niveles and len(r["si"]) == 1 and r["si"][0] in cuadros:
            m_cu[cuadros.index(r["si"][0])][niveles.index(r["entonces"])] = 1
    return sintomas, cuadros, niveles, m_sc, m_cu


def producto_booleano(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    return [[int(any(a[i][k] and b[k][j] for k in range(len(b))))
             for j in range(len(b[0]))] for i in range(len(a))]


def matrices_seguro() -> tuple[list[str], list[str], list[str], list[list[int]], list[list[int]], list[list[int]]]:
    """Composición de relaciones  seguro → institución → establecimiento.

    M_SI: seguro × institución        (1 si el seguro acepta esa institución)
    M_IE: institución × establecimiento (1 si el establecimiento es de esa institución)
    M_SE = M_SI ⊙ M_IE: seguro × establecimiento (producto booleano: qué establecimientos cubre cada seguro)
    """
    seg = datos_seguros()
    instituciones = list(cargar("seguros")["instituciones"])
    establecimientos = list(cargar("grafo")["establecimientos"])
    ids_seguros = list(seg)
    m_si = [[int(i in seg[s]["instituciones"]) for i in instituciones] for s in ids_seguros]
    m_ie = [[int(cargar("grafo")["establecimientos"][e].get("institucion") == i) for e in establecimientos]
            for i in instituciones]
    return ids_seguros, instituciones, establecimientos, m_si, m_ie, producto_booleano(m_si, m_ie)


def cubiertos_por_instituciones(instituciones: list[str]) -> list[str]:
    """Establecimientos de las instituciones dadas: un vector fila (1 × instituciones) por M_IE."""
    _, todas, establecimientos, _, m_ie, _ = matrices_seguro()
    fila = [[int(i in instituciones) for i in todas]]
    return [e for e, v in zip(establecimientos, producto_booleano(fila, m_ie)[0]) if v]


def destinos_por_seguro(seguro: str, aceptables: set[str]) -> tuple[list[str], str]:
    """Destinos = (establecimientos aceptados por el nivel) ∩ (establecimientos que cubre el seguro).

    Devuelve (ids ordenados, línea de traza con la composición)."""
    ids_seguros, _, establecimientos, _, _, m_se = matrices_seguro()
    fila = m_se[ids_seguros.index(seguro)]
    cubiertos = [e for e, v in zip(establecimientos, fila) if v]
    destinos = sorted(set(cubiertos) & aceptables)
    inst = datos_seguros()[seguro]["instituciones"]
    traza = (f"Seguro {seguro} → instituciones {inst} → establecimientos {cubiertos} "
             f"∩ nivel {sorted(aceptables)} = {destinos}")
    return destinos, traza


def candidatos(presentes: set[str]) -> list[str]:
    sintomas, cuadros, _, m_sc, _ = matrices()
    return [c for j, c in enumerate(cuadros)
            if any(m_sc[sintomas.index(s)][j] for s in presentes if s in sintomas)]


# ---------- «¿Por qué me preguntas esto?» ----------
def cuadros_con_literal(literal: str) -> set[str]:
    """Cuadros que tienen ese literal en alguna de sus reglas: la regla que los concluye lo trae como premisa
    (afirmada o negada), o una regla de riesgo lo combina con el cuadro (p. ej. «dengue ∧ menor_5»)."""
    cuadros = set(datos_cuadros())
    hallados: set[str] = set()
    for regla in cargar("reglas")["reglas"]:
        premisas = {p.lstrip("~") for p in regla["si"]}
        if literal in premisas:
            if regla["entonces"] in cuadros:
                hallados.add(regla["entonces"])
            hallados |= premisas & cuadros
    return hallados


def literales_de_pregunta(id_: str) -> set[str]:
    """Los literales sobre los que informa una pregunta: un síntoma o factor es él mismo; el grupo de edad, los
    literales de edad; una pregunta de opciones, los literales que agregan sus opciones."""
    especial = preguntas_especiales().get(id_)
    if especial is None:
        return {id_}
    if especial["tipo"] == "grupo":
        return set(literales_edad())
    return {lit for op in especial.get("opciones", []) for k in ("presentes", "ausentes") for lit in op.get("efecto", {}).get(k, [])}


def cuadros_de_pregunta(id_: str, presentes: set[str]) -> list[str]:
    """Los cuadros candidatos ACTUALES (los que comparten algún síntoma con lo que el usuario ya dijo) que tienen
    en sus reglas el literal por el que se pregunta. Si ninguno de los candidatos lo tiene, todos los que lo tienen."""
    con_el_literal: set[str] = set()
    for lit in literales_de_pregunta(id_):
        con_el_literal |= cuadros_con_literal(lit)
    actuales = set(candidatos(presentes))
    return sorted((con_el_literal & actuales) or con_el_literal)


def afecta_la_urgencia(id_: str) -> bool:
    """¿Alguna regla que concluye un nivel de urgencia usa este literal (solo o con un cuadro)?"""
    niveles = set(cargar("reglas")["niveles_urgencia"])
    lits = literales_de_pregunta(id_)
    return any(regla["entonces"] in niveles and lits & {p.lstrip("~") for p in regla["si"]}
               for regla in cargar("reglas")["reglas"])
