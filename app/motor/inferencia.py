"""Motor de inferencia: encadenamiento hacia adelante con modus ponens y traza.

Terminación (por inducción): sea H_k el conjunto de hechos tras la iteración k.
H_k ⊆ H_{k+1} ⊆ U, con U = hechos iniciales ∪ conclusiones de las reglas (finito).
Si una iteración no agrega hechos, el algoritmo se detiene; si agrega, |H| crece
en al menos 1. Como |H| ≤ |U|, hay a lo sumo |reglas| + 1 iteraciones.
"""
from app import datos
from app.datos import cargar


def literales(presentes: set[str], ausentes: set[str]) -> set[str]:
    return set(presentes) | {f"~{a}" for a in ausentes}


def inferir(hechos_iniciales: set[str]) -> tuple[set[str], list[str], int]:
    reglas = cargar("reglas")["reglas"]
    hechos = set(hechos_iniciales)
    traza: list[str] = []
    disparadas: set[str] = set()
    iteraciones = 0
    while True:
        iteraciones += 1
        nuevos = False
        for r in reglas:
            if r["id"] in disparadas:
                continue
            if all(p in hechos for p in r["si"]):
                disparadas.add(r["id"])
                if r["entonces"] not in hechos:
                    hechos.add(r["entonces"])
                    nuevos = True
                    linea = f"{r['id']}: {' ∧ '.join(r['si'])} → {r['entonces']}  (modus ponens)"
                    if r.get("explicacion"):   # las reglas con fuente citan su explicación
                        linea += f" — {r['explicacion']}" + (f" [{r['fuente']}]" if r.get("fuente") else "")
                    traza.append(linea)
        if not nuevos:
            break
    assert iteraciones <= len(reglas) + 1, "violación de la cota de terminación"
    return hechos, traza, iteraciones


def urgencia(hechos: set[str]) -> str | None:
    """Si varias reglas concluyen urgencias distintas, gana la mayor (fallar hacia la seguridad)."""
    niveles = cargar("reglas")["niveles_urgencia"]
    encontradas = [n for n in niveles if n in hechos]
    return encontradas[-1] if encontradas else None


def cuadros(hechos: set[str]) -> list[str]:
    """Cuadros concluidos (los que tienen ficha en data/cuadros.json)."""
    return sorted(h for h in hechos if h in datos.cuadros())
