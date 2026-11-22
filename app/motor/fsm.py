"""Máquina de Mealy del chat: M = (Q, Σ, Λ, δ, λ, q0).

La salida depende del estado Y de la entrada (por eso Mealy y no Moore).
Σ no es el texto del usuario (infinito), sino la CLASE que le asigna el
clasificador, que es un alfabeto finito. δ es TOTAL: definida para todo
par (estado, símbolo), así ninguna entrada deja al sistema sin respuesta.

Estados:
  SALUDO      inicio.                         TRIAJE    preguntas de síntomas.
  SEGURO      espera el seguro del usuario.   UBICACION espera la ubicación del usuario.
  DERIVACION  hay una conclusión o una ruta.  ERROR     entrada no entendida al inicio.

Símbolos de entrada:
  vacio, invalido, sintomas, respuesta (sí/no a una pregunta), alarma  — como siempre;
  conclusion      el triaje terminó (lo genera el sistema);
  buscar_centro   el usuario pide un establecimiento, o el sistema ofrece buscarlo → hay que preguntar el seguro;
  seguro          el seguro quedó resuelto: lo dio el usuario, ya se conocía, o no hace falta (emergencia, Ley 27604)
                  → se pide la ubicación;
  ubicacion       llegó la ubicación (o se supo que no se compartirá);
  incompleto      el mensaje dice que algo le pasa pero no qué ("tengo dolor", "me siento mal"): se aclara;
  confirmar       el usuario confirma el resumen de lo que entendió → ahora sí se concluye;
  corregir        el usuario quiere corregir ese resumen (quitar un síntoma o agregar otro);
  deshacer        «Me equivoqué»: se restaura el estado anterior (pila de la sesión);
  explicar        «¿Por qué?»: se explica la pregunta pendiente sin avanzar la conversación.
"""
Q = ["SALUDO", "TRIAJE", "SEGURO", "UBICACION", "DERIVACION", "ERROR"]
SIGMA = ["vacio", "invalido", "sintomas", "respuesta", "alarma", "conclusion", "buscar_centro", "seguro", "ubicacion",
         "incompleto", "confirmar", "corregir", "deshacer", "explicar"]
Q0 = "SALUDO"

# (estado, símbolo) -> (estado siguiente, salida)
DELTA: dict[tuple[str, str], tuple[str, str]] = {
    ("SALUDO", "vacio"):          ("SALUDO", "saludar"),
    ("SALUDO", "invalido"):       ("ERROR", "ayuda"),
    ("SALUDO", "sintomas"):       ("TRIAJE", "preguntar"),
    ("SALUDO", "respuesta"):      ("ERROR", "ayuda"),
    ("SALUDO", "alarma"):         ("DERIVACION", "emergencia"),
    ("SALUDO", "conclusion"):     ("DERIVACION", "derivar"),
    ("SALUDO", "buscar_centro"):  ("SEGURO", "pedir_seguro"),
    ("SALUDO", "seguro"):         ("UBICACION", "pedir_ubicacion"),
    ("SALUDO", "ubicacion"):      ("ERROR", "ayuda"),
    ("SALUDO", "incompleto"):     ("TRIAJE", "aclarar"),
    ("SALUDO", "confirmar"):      ("SALUDO", "ayuda"),
    ("SALUDO", "corregir"):       ("SALUDO", "ayuda"),
    ("SALUDO", "deshacer"):       ("SALUDO", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("SALUDO", "explicar"):       ("SALUDO", "explicar"),   # no cambia de estado ni consume turno

    ("TRIAJE", "vacio"):          ("TRIAJE", "repetir"),
    ("TRIAJE", "invalido"):       ("TRIAJE", "repetir"),
    ("TRIAJE", "sintomas"):       ("TRIAJE", "preguntar"),
    ("TRIAJE", "respuesta"):      ("TRIAJE", "preguntar"),
    ("TRIAJE", "alarma"):         ("DERIVACION", "emergencia"),
    ("TRIAJE", "conclusion"):     ("DERIVACION", "derivar"),
    ("TRIAJE", "buscar_centro"):  ("SEGURO", "pedir_seguro"),
    ("TRIAJE", "seguro"):         ("UBICACION", "pedir_ubicacion"),
    ("TRIAJE", "ubicacion"):      ("TRIAJE", "mostrar_ruta"),     # reintento de la ruta en mitad del triaje
    ("TRIAJE", "incompleto"):     ("TRIAJE", "aclarar"),
    ("TRIAJE", "confirmar"):      ("DERIVACION", "concluir"),
    ("TRIAJE", "corregir"):       ("TRIAJE", "corregir"),
    ("TRIAJE", "deshacer"):       ("TRIAJE", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("TRIAJE", "explicar"):       ("TRIAJE", "explicar"),   # no cambia de estado ni consume turno

    ("SEGURO", "vacio"):          ("SEGURO", "repetir_seguro"),
    ("SEGURO", "invalido"):       ("SEGURO", "repetir_seguro"),
    ("SEGURO", "sintomas"):       ("SALUDO", "reiniciar"),
    ("SEGURO", "respuesta"):      ("SEGURO", "repetir_seguro"),
    ("SEGURO", "alarma"):         ("DERIVACION", "emergencia"),
    ("SEGURO", "conclusion"):     ("SEGURO", "ayuda"),
    ("SEGURO", "buscar_centro"):  ("SEGURO", "pedir_seguro"),
    ("SEGURO", "seguro"):         ("UBICACION", "pedir_ubicacion"),
    ("SEGURO", "ubicacion"):      ("SEGURO", "repetir_seguro"),
    ("SEGURO", "incompleto"):     ("SEGURO", "repetir_seguro"),
    ("SEGURO", "confirmar"):      ("SEGURO", "repetir_seguro"),
    ("SEGURO", "corregir"):       ("SEGURO", "repetir_seguro"),
    ("SEGURO", "deshacer"):       ("SEGURO", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("SEGURO", "explicar"):       ("SEGURO", "explicar"),   # no cambia de estado ni consume turno

    ("UBICACION", "vacio"):         ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "invalido"):      ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "sintomas"):      ("SALUDO", "reiniciar"),
    ("UBICACION", "respuesta"):     ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "alarma"):        ("DERIVACION", "emergencia"),
    ("UBICACION", "conclusion"):    ("UBICACION", "ayuda"),
    ("UBICACION", "buscar_centro"): ("UBICACION", "pedir_ubicacion"),
    ("UBICACION", "seguro"):        ("UBICACION", "pedir_ubicacion"),
    ("UBICACION", "ubicacion"):     ("DERIVACION", "mostrar_ruta"),
    ("UBICACION", "incompleto"):    ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "confirmar"):     ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "corregir"):      ("UBICACION", "repetir_ubicacion"),
    ("UBICACION", "deshacer"):    ("UBICACION", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("UBICACION", "explicar"):    ("UBICACION", "explicar"),   # no cambia de estado ni consume turno

    ("DERIVACION", "vacio"):      ("SALUDO", "reiniciar"),
    ("DERIVACION", "invalido"):   ("SALUDO", "reiniciar"),
    ("DERIVACION", "sintomas"):   ("SALUDO", "reiniciar"),
    ("DERIVACION", "respuesta"):  ("DERIVACION", "cerrar"),      # "no" a la oferta de un centro de salud
    ("DERIVACION", "alarma"):     ("DERIVACION", "emergencia"),
    ("DERIVACION", "conclusion"): ("DERIVACION", "derivar"),
    ("DERIVACION", "buscar_centro"): ("SEGURO", "pedir_seguro"),
    ("DERIVACION", "seguro"):     ("UBICACION", "pedir_ubicacion"),
    ("DERIVACION", "ubicacion"):  ("DERIVACION", "mostrar_ruta"),  # también reintenta la ruta si falló la ubicación
    ("DERIVACION", "incompleto"): ("SALUDO", "reiniciar"),
    ("DERIVACION", "confirmar"):  ("DERIVACION", "ayuda"),
    ("DERIVACION", "corregir"):   ("DERIVACION", "ayuda"),
    ("DERIVACION", "deshacer"):   ("DERIVACION", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("DERIVACION", "explicar"):   ("DERIVACION", "explicar"),   # no cambia de estado ni consume turno

    ("ERROR", "vacio"):           ("ERROR", "ayuda"),
    ("ERROR", "invalido"):        ("ERROR", "ayuda"),
    ("ERROR", "sintomas"):        ("TRIAJE", "preguntar"),
    ("ERROR", "respuesta"):       ("ERROR", "ayuda"),
    ("ERROR", "alarma"):          ("DERIVACION", "emergencia"),
    ("ERROR", "conclusion"):      ("DERIVACION", "derivar"),
    ("ERROR", "buscar_centro"):   ("SEGURO", "pedir_seguro"),
    ("ERROR", "seguro"):          ("UBICACION", "pedir_ubicacion"),
    ("ERROR", "ubicacion"):       ("ERROR", "ayuda"),
    ("ERROR", "incompleto"):      ("TRIAJE", "aclarar"),
    ("ERROR", "confirmar"):       ("ERROR", "ayuda"),
    ("ERROR", "corregir"):        ("ERROR", "ayuda"),
    ("ERROR", "deshacer"):        ("ERROR", "deshacer"),   # el estado real lo restaura la pila (Mealy con memoria)
    ("ERROR", "explicar"):        ("ERROR", "explicar"),   # no cambia de estado ni consume turno
}


def paso(estado: str, simbolo: str) -> tuple[str, str]:
    return DELTA[(estado, simbolo)]


def es_total() -> bool:
    return all((q, s) in DELTA for q in Q for s in SIGMA)
