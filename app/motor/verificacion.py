"""Verificación de la base de conocimiento: tablas de verdad ACOTADAS y restricciones de integridad.

No se construye la tabla de 2^n filas con todos los síntomas: para cada regla
y para cada par de reglas solo se usan las variables que aparecen en ellas.

Restricciones (DISENO_BD.md §4). Cada una es una función pura sobre sus datos y devuelve
la lista de problemas encontrados (vacía = se cumple):

  I1  todo literal de una regla existe en sintomas, factores_riesgo o cuadros   (función bien definida)
  I2  todo cuadro tiene una regla diagnóstica y una de urgencia                 (sobreyectiva sobre cuadros)
  I3  todo nodo del árbol pregunta por un síntoma o factor existente            (integridad referencial)
  I4  ninguna regla tiene premisas contradictorias p ∧ ~p                       (satisfacibilidad)
  I5  ningún par de reglas concluye q y ~q pudiendo dispararse juntas           (tabla de verdad acotada)
  I6  el grafo es conexo                                                         (grafos)
  I7  desde todo distrito se alcanza un establecimiento de cada nivel           (alcanzabilidad)
  I8  todo establecimiento y toda vía apuntan a distritos que existen           (función total)
  I9  todo id es único dentro de su archivo (y no se repite entre archivos)     (clave primaria)
  I10 MAX_TURNOS ≥ altura(arbol)                                                 (terminación)
  I11 (extra) niveles.json coincide con las reglas, y urgencia_base de cada cuadro con su regla de urgencia
  I13 (extra) cada establecimiento tiene institución; los seguros solo nombran instituciones declaradas
  I14 (extra) los grupos de edad son una partición (disjuntos dos a dos y cubren todas las edades)
  I12 (extra) con red de calles: cada establecimiento tiene un nodo válido y a ≤ 150 m (zona.json); la zona cubre sus puntos de control
"""
import json
import sys
from collections import Counter
from itertools import product

from app import datos
from app.datos import DATA, cargar
from app.motor import arbol, grafo, red_vial


def _var(lit: str) -> str:
    return lit.lstrip("~")


def _valor(lit: str, asignacion: dict[str, bool]) -> bool:
    v = asignacion[_var(lit)]
    return not v if lit.startswith("~") else v


def satisfacible(premisas: list[str]) -> bool:
    variables = sorted({_var(p) for p in premisas})
    for fila in product([False, True], repeat=len(variables)):
        a = dict(zip(variables, fila))
        if all(_valor(p, a) for p in premisas):
            return True
    return False


# ---------- I1 – I5: reglas y árbol ----------
def i1_literales_conocidos(reglas: list[dict], conocidos: set[str], conclusiones: set[str]) -> list[str]:
    problemas = []
    for r in reglas:
        for lit in r["si"]:
            if _var(lit) not in conocidos:
                problemas.append(f"I1: {r['id']} usa '{lit}', que no existe en sintomas, factores_riesgo ni cuadros")
        if r["entonces"] not in conclusiones:
            problemas.append(f"I1: {r['id']} concluye '{r['entonces']}', que no es un cuadro ni un nivel de urgencia")
    return problemas


def i2_cuadros_con_reglas(reglas: list[dict], cuadros: set[str], niveles: set[str]) -> list[str]:
    problemas = []
    for c in sorted(cuadros):
        if not any(r["entonces"] == c for r in reglas):
            problemas.append(f"I2: el cuadro '{c}' no tiene ninguna regla diagnóstica")
        if not any(r["entonces"] in niveles and r["si"] == [c] for r in reglas):
            problemas.append(f"I2: el cuadro '{c}' no tiene ninguna regla de urgencia")
    return problemas


def i3_arbol_referencias(preguntados: set[str], conocidos: set[str], alarma: list[str], factores: list[str],
                         ids_alarma: set[str], ids_factores: set[str]) -> list[str]:
    problemas = [f"I3: el árbol pregunta por '{p}', que no existe en sintomas ni factores_riesgo"
                 for p in sorted(preguntados - conocidos)]
    problemas += [f"I3: '{a}' está en la lista 'alarma' del árbol pero no es un signo de alarma"
                  for a in alarma if a not in ids_alarma]
    problemas += [f"I3: '{f}' está en la lista 'factores' del árbol pero no es un factor de riesgo"
                  for f in factores if f not in ids_factores]
    return problemas


def i3_preguntas_especiales(arbol_datos: dict, especiales: dict, literales: set[str]) -> list[str]:
    """Parte de I3: los seguimientos del árbol y los efectos de las opciones apuntan a cosas que existen."""
    problemas = []
    for sg in arbol_datos.get("seguimientos", []):
        if sg["si"] not in literales:
            problemas.append(f"I3: el seguimiento dispara por '{sg['si']}', que no es un síntoma ni un factor")
        if sg["pregunta"] not in especiales:
            problemas.append(f"I3: el seguimiento pregunta '{sg['pregunta']}', que no está en preguntas.json")
    for pid, q in especiales.items():
        ids = [o["id"] for o in q.get("opciones", [])]
        if len(ids) != len(set(ids)):
            problemas.append(f"I3: la pregunta '{pid}' repite el id de una opción")
        for o in q.get("opciones", []):
            for lit in o.get("efecto", {}).get("presentes", []) + o.get("efecto", {}).get("ausentes", []):
                if lit not in literales:
                    problemas.append(f"I3: la opción '{o['id']}' de '{pid}' afecta a '{lit}', que no existe")
    return problemas


def i4_premisas_satisfacibles(reglas: list[dict]) -> tuple[list[str], int]:
    problemas, filas = [], 0
    for r in reglas:
        filas += 2 ** len({_var(p) for p in r["si"]})
        if not satisfacible(r["si"]):
            problemas.append(f"I4: {r['id']}: premisas contradictorias")
    return problemas, filas


def i5_conclusiones_complementarias(reglas: list[dict]) -> tuple[list[str], int]:
    problemas, filas = [], 0
    for i, r1 in enumerate(reglas):
        for r2 in reglas[i + 1:]:
            c1, c2 = r1["entonces"], r2["entonces"]
            if _var(c1) == _var(c2) and c1 != c2:  # q y ~q
                juntas = r1["si"] + r2["si"]
                filas += 2 ** len({_var(p) for p in juntas})
                if satisfacible(juntas):
                    problemas.append(f"I5: {r1['id']} y {r2['id']} pueden concluir {c1} y {c2} a la vez")
    return problemas, filas


# ---------- I6 – I8: grafo ----------
def i8_referencias_grafo(g: dict) -> list[str]:
    distritos = set(g["distritos"])
    problemas = []
    for eid, e in g["establecimientos"].items():
        if e["distrito"] not in distritos:
            problemas.append(f"I8: el establecimiento '{eid}' cuelga del distrito '{e['distrito']}', que no existe")
        if e["minutos"] < 0:
            problemas.append(f"I8: el establecimiento '{eid}' tiene un peso negativo")
    for a, b, w in g["vias"]:
        for extremo in (a, b):
            if extremo not in distritos:
                problemas.append(f"I8: la vía {a}–{b} usa '{extremo}', que no es un distrito")
        if w < 0:
            problemas.append(f"I8: la vía {a}–{b} tiene un peso negativo")
    return problemas


def i6_grafo_conexo(adj: dict) -> list[str]:
    if not adj:
        return []
    visitados, pila = set(), [next(iter(adj))]
    while pila:
        v = pila.pop()
        if v not in visitados:
            visitados.add(v)
            pila += [w for w, _ in adj[v] if w not in visitados]
    aislados = sorted(set(adj) - visitados)
    return [f"I6: el grafo no es conexo; no se llega a {aislados}"] if aislados else []


def i7_alcanzabilidad(g: dict, adj: dict, definiciones: dict) -> list[str]:
    problemas = []
    for nivel, n in definiciones.items():
        if n.get("ruta_opcional"):
            continue
        destinos = [e for e, d in g["establecimientos"].items() if grafo.aceptable(d, nivel, definiciones)]
        for distrito in g["distritos"]:
            dist, _ = grafo.dijkstra(adj, distrito)
            if not any(dist[e] < float("inf") for e in destinos):
                problemas.append(f"I7: desde '{distrito}' no se alcanza ningún establecimiento aceptable para {nivel}")
    return problemas


# ---------- I9, I10, I11 ----------
def claves_repetidas(nombre: str) -> list[str]:
    """Claves repetidas dentro de un mismo objeto del JSON (json.load las funde sin avisar)."""
    repetidas: list[str] = []

    def hook(pares):
        for clave, n in Counter(k for k, _ in pares).items():
            if n > 1:
                repetidas.append(f"{nombre}.json repite la clave '{clave}'")
        return dict(pares)

    with open(DATA / f"{nombre}.json", encoding="utf-8") as f:
        json.load(f, object_pairs_hook=hook)
    return repetidas


def i9_ids_unicos(ids_reglas: list[str], repetidas: list[str], grupos: list[dict[str, set[str]]],
                  reservados: set[str]) -> list[str]:
    """Ids únicos en cada archivo. Además, dentro de un grupo de archivos que comparten espacio de nombres
    (los literales de las reglas, o los nodos del grafo) un id no puede estar en dos archivos."""
    problemas = [f"I9: reglas.json repite el id '{i}'" for i, n in Counter(ids_reglas).items() if n > 1]
    problemas += [f"I9: {r}" for r in repetidas]
    for espacios in grupos:
        nombres = list(espacios)
        for i, a in enumerate(nombres):
            for b in nombres[i + 1:]:
                for comun in sorted(espacios[a] & espacios[b]):
                    problemas.append(f"I9: el id '{comun}' está en {a} y en {b}")
            for r in sorted(espacios[a] & reservados):
                problemas.append(f"I9: el id '{r}' de {a} está reservado")
    return problemas


def i10_terminacion(max_turnos: int, altura_arbol: int) -> list[str]:
    if max_turnos < altura_arbol:
        return [f"I10: MAX_TURNOS ({max_turnos}) es menor que la altura del árbol ({altura_arbol})"]
    return []


def i11_coherencia(reglas: list[dict], niveles_orden: list[str], definiciones: dict, cuadros: dict) -> list[str]:
    problemas = []
    if set(definiciones) != set(niveles_orden):
        problemas.append(f"I11: niveles.json {sorted(definiciones)} no coincide con niveles_urgencia "
                         f"de reglas.json {sorted(niveles_orden)}")
    for c, ficha in cuadros.items():
        concluidos = {r["entonces"] for r in reglas if r["si"] == [c] and r["entonces"] in niveles_orden}
        if concluidos and concluidos != {ficha["urgencia_base"]}:
            problemas.append(f"I11: urgencia_base de '{c}' es {ficha['urgencia_base']} pero sus reglas de urgencia "
                             f"concluyen {sorted(concluidos)}")
    return problemas


def i12_red_vial(g: dict, nodos: list | None, z: dict) -> list[str]:
    """I12 (extra) Si existe la red de calles, cada establecimiento apunta a un nodo válido, con su distancia
    al día y a no más de 'max_distancia_establecimiento_nodo_m' (zona.json) de esa calle; y los puntos de control están dentro del radio.
    Sin red_lima.json no hay nada que comprobar (se usa el grafo de distritos)."""
    if nodos is None:
        return []
    problemas = []
    centro = (z["centro"]["lat"], z["centro"]["lng"])
    for p in z["puntos_de_control"]:
        if red_vial.haversine(centro, (p["lat"], p["lng"])) > z["radio_m"]:
            problemas.append(f"I12: el punto de control '{p['nombre']}' está fuera del radio de la zona")
    arreglo = "corre: python scripts/descargar_red.py --solo-asignar"
    for eid, e in g["establecimientos"].items():
        nodo = e.get("nodo")
        if not isinstance(nodo, int) or isinstance(nodo, bool) or not 0 <= nodo < len(nodos):
            problemas.append(f"I12: el establecimiento '{eid}' no tiene un 'nodo' válido de la red vial ({arreglo})")
            continue
        metros = red_vial.haversine((e["lat"], e["lng"]), tuple(nodos[nodo]))
        if abs(metros - e.get("distancia_nodo_m", float("inf"))) > 1:
            problemas.append(f"I12: el nodo o la distancia de '{eid}' están desactualizados ({arreglo})")
        elif metros > z["max_distancia_establecimiento_nodo_m"]:
            problemas.append(f"I12: '{eid}' está a {metros:.1f} m de su calle más cercana (máximo "
                             f"{z['max_distancia_establecimiento_nodo_m']} m): sus coordenadas son incorrectas, revísalas")
    return problemas


def i13_seguros_e_instituciones(g: dict, cfg: dict) -> list[str]:
    """I13 (extra) Cada establecimiento tiene 'institucion', y todo lo que el seguro nombra existe:
    las instituciones de cada seguro y las de respaldo están declaradas, y cada seguro tiene claves y etiqueta."""
    declaradas = set(cfg["instituciones"])
    problemas = []
    for eid, e in g["establecimientos"].items():
        if e.get("institucion") not in declaradas:
            problemas.append(f"I13: el establecimiento '{eid}' no tiene una 'institucion' válida {sorted(declaradas)}")
    for sid, s in cfg["seguros"].items():
        for i in s["instituciones"]:
            if i not in declaradas:
                problemas.append(f"I13: el seguro '{sid}' acepta la institución '{i}', que no está declarada")
        if not s["claves"] or not s["etiqueta"]:
            problemas.append(f"I13: el seguro '{sid}' necesita etiqueta y claves")
    for i in cfg["respaldo_instituciones"]:
        if i not in declaradas:
            problemas.append(f"I13: el respaldo usa la institución '{i}', que no está declarada")
    return problemas


def i14_particion_edades(grupos: dict, literales_conocidos: set[str]) -> list[str]:
    """I14 (extra) Los grupos de edad son una PARTICIÓN: cada intervalo [desde, hasta) es válido, dos a dos no se
    traslapan (disjuntos) y su unión cubre desde 0 hasta el infinito (toda edad cae en uno y solo uno)."""
    infinito = float("inf")
    tramos = {gid: (g["desde_meses"], infinito if g["hasta_meses"] is None else g["hasta_meses"]) for gid, g in grupos.items()}
    problemas = [f"I14: el grupo '{gid}' tiene un intervalo vacío o invertido [{d}, {h})" for gid, (d, h) in tramos.items() if d >= h]
    ids = list(tramos)
    for i, a in enumerate(ids):                                          # disjuntos dos a dos
        for b in ids[i + 1:]:
            (a1, a2), (b1, b2) = tramos[a], tramos[b]
            if a1 < b2 and b1 < a2:
                problemas.append(f"I14: los grupos '{a}' y '{b}' se traslapan")
    cursor = 0                                                           # la unión cubre [0, ∞)
    for gid, (d, h) in sorted(tramos.items(), key=lambda kv: kv[1]):
        if d > cursor:
            problemas.append(f"I14: ningún grupo cubre las edades entre {cursor} y {d} meses (antes de '{gid}')")
        cursor = max(cursor, h)
    if cursor != infinito:
        problemas.append(f"I14: ningún grupo cubre las edades desde {cursor} meses en adelante")
    for gid, g in grupos.items():
        for lit in g["literales"] + g["no_aplica"]:
            if lit not in literales_conocidos:
                problemas.append(f"I14: el grupo '{gid}' usa '{lit}', que no existe como factor de riesgo")
    return problemas


def advertencias_de_datos(reglas: list[dict], sintomas: dict, factores: dict) -> list[str]:
    """Avisos que NO invalidan la base pero conviene que el equipo revise."""
    avisos = []
    dueños: dict[str, list[str]] = {}
    for sid, d in {**sintomas, **factores}.items():
        for clave in d["claves"]:
            dueños.setdefault(clave, []).append(sid)
    for clave, ids in sorted(dueños.items()):
        if len(ids) > 1:
            avisos.append(f"la clave '{clave}' está en {ids}; el extractor usa solo la primera ('{ids[0]}')")
    n = sum(1 for r in reglas if r.get("revisar"))
    if n:
        avisos.append(f"{n} reglas siguen marcadas revisar=true (pendientes de validación del equipo)")
    return avisos


# ---------- orquestación ----------
def verificar(max_turnos: int | None = None) -> dict:
    if max_turnos is None:
        from app.main import MAX_TURNOS   # import tardío: main importa este módulo al arrancar
        max_turnos = MAX_TURNOS

    cfg = cargar("reglas")
    reglas, niveles_orden = cfg["reglas"], cfg["niveles_urgencia"]
    sint, fact, cuad, niv = datos.sintomas(), datos.factores(), datos.cuadros(), datos.niveles()
    g, arbol_datos = cargar("grafo"), cargar("arbol")
    conocidos = set(sint) | set(fact) | set(cuad)

    por_restriccion: dict[str, list[str]] = {}
    por_restriccion["I1"] = i1_literales_conocidos(reglas, conocidos, set(cuad) | set(niv))
    por_restriccion["I2"] = i2_cuadros_con_reglas(reglas, set(cuad), set(niv))
    especiales = set(datos.preguntas_especiales())     # preguntas que no son sí/no (grupo_edad...)
    por_restriccion["I3"] = i3_arbol_referencias(arbol.preguntados(), set(sint) | set(fact) | especiales, arbol_datos["alarma"],
                                                 arbol_datos["factores"], datos.ids_alarma(), set(fact) | especiales)
    por_restriccion["I3"] += i3_preguntas_especiales(arbol_datos, datos.preguntas_especiales(), set(sint) | set(fact))
    p4, filas4 = i4_premisas_satisfacibles(reglas)
    p5, filas5 = i5_conclusiones_complementarias(reglas)
    por_restriccion["I4"], por_restriccion["I5"] = p4, p5

    por_restriccion["I8"] = i8_referencias_grafo(g)
    if por_restriccion["I8"]:   # sin referencias válidas no se puede armar el grafo
        omitida = ["no evaluada: el grafo tiene referencias rotas (ver I8)"]
        por_restriccion["I6"], por_restriccion["I7"] = list(omitida), list(omitida)
    else:
        adj = grafo.construir(g)
        por_restriccion["I6"] = i6_grafo_conexo(adj)
        por_restriccion["I7"] = i7_alcanzabilidad(g, adj, niv)

    repetidas = [r for n in ("sintomas", "factores_riesgo", "cuadros", "niveles", "grafo", "reglas")
                 for r in claves_repetidas(n)]
    por_restriccion["I9"] = i9_ids_unicos(
        [r["id"] for r in reglas], repetidas,
        [{"sintomas": set(sint), "factores_riesgo": set(fact), "cuadros": set(cuad), "niveles": set(niv)},
         {"distritos": set(g["distritos"]), "establecimientos": set(g["establecimientos"])}],
        reservados={grafo.USUARIO})
    por_restriccion["I10"] = i10_terminacion(max_turnos, arbol.altura_total())
    por_restriccion["I11"] = i11_coherencia(reglas, niveles_orden, niv, cuad)
    red = red_vial.cargar_red()
    por_restriccion["I12"] = i12_red_vial(g, red.nodos if red else None, datos.zona())
    por_restriccion["I13"] = i13_seguros_e_instituciones(g, cargar("seguros"))
    por_restriccion["I14"] = i14_particion_edades(datos.grupos_edad(), set(fact))

    problemas = [p for lista in por_restriccion.values() for p in lista]
    return {
        "consistente": not problemas,
        "problemas": problemas,
        "filas_evaluadas": filas4 + filas5,
        "restricciones": {k: not v for k, v in sorted(por_restriccion.items(), key=lambda kv: int(kv[0][1:]))},
        "advertencias": advertencias_de_datos(reglas, sint, fact)
        + ([] if red else ["no existe data/red_lima.json: las rutas usan el grafo de distritos (python scripts/descargar_red.py)"]),
    }


if __name__ == "__main__":
    r = verificar()
    print(f"consistente: {r['consistente']}   filas de tabla de verdad evaluadas: {r['filas_evaluadas']}")
    print("restricciones:", "  ".join(f"{k}={'ok' if ok else 'FALLA'}" for k, ok in r["restricciones"].items()))
    for p in r["problemas"]:
        print("  ✗", p)
    for a in r["advertencias"]:
        print("  ! advertencia:", a)
    sys.exit(0 if r["consistente"] else 1)
