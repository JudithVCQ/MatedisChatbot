"""Tolerancia a errores de ortografía: distancia de Levenshtein propia y su uso en el extractor."""
import random
from functools import lru_cache

import pytest

from app.motor import extractor_keywords as kw, levenshtein as lv
from tests.ayudas import enviar, nueva, tiene_accion


@pytest.fixture(autouse=True)
def limitador_limpio():
    from app.main import peticiones
    peticiones.clear()


# ---------- la distancia ----------
def referencia(a: str, b: str) -> int:
    """Definición recursiva de la distancia (con memoria): sirve de oráculo para la versión de programación dinámica."""
    @lru_cache(maxsize=None)
    def d(i, j):
        if i == 0:
            return j
        if j == 0:
            return i
        return min(d(i - 1, j) + 1, d(i, j - 1) + 1, d(i - 1, j - 1) + (a[i - 1] != b[j - 1]))
    return d(len(a), len(b))


@pytest.mark.parametrize("a, b, esperada", [
    ("kitten", "sitting", 3), ("fievre", "fiebre", 1), ("diarea", "diarrea", 1), ("cabesa", "cabeza", 1), ("peho", "pecho", 1),
    ("feibre", "fiebre", 2),                       # un intercambio de letras vecinas cuenta 2
    ("", "", 0), ("", "abc", 3), ("abc", "", 3), ("tos", "tos", 0), ("los", "tos", 1), ("flaw", "lawn", 2),
])
def test_distancia_con_valores_conocidos(a, b, esperada):
    assert lv.distancia(a, b) == esperada


def test_distancia_coincide_con_la_definicion_recursiva_y_es_una_metrica():
    azar = random.Random(7)
    palabras = ["".join(azar.choice("abcde") for _ in range(azar.randint(0, 7))) for _ in range(80)]
    for a in palabras:
        assert lv.distancia(a, a) == 0
        for b in palabras[:25]:
            d = lv.distancia(a, b)
            assert d == referencia(a, b) and d == lv.distancia(b, a)                       # = definición; simétrica
            assert abs(len(a) - len(b)) <= d <= max(len(a), len(b))                         # cotas
            assert (d == 0) == (a == b)
    for a, b, c in zip(palabras, palabras[1:], palabras[2:]):
        assert lv.distancia(a, c) <= lv.distancia(a, b) + lv.distancia(b, c)               # desigualdad triangular


@pytest.mark.parametrize("largo, umbral", [(1, 0), (3, 0), (4, 0), (5, 1), (6, 1), (7, 1), (8, 2), (9, 2), (15, 2)])
def test_umbral_segun_el_largo(largo, umbral):
    assert lv.umbral(largo) == umbral


VOCAB = {"fiebre": {"fiebre"}, "tos": {"tos"}, "pecho": {"dolor_pecho"}, "congestion": {"congestion_nasal"}, "cabeza": {"dolor_cabeza"}}


@pytest.mark.parametrize("palabra, esperada", [
    ("fievre", ("fiebre", 1)), ("peho", ("pecho", 1)), ("cabesa", ("cabeza", 1)),
    ("congetsion", ("congestion", 2)),        # 10 letras: hasta 2 ediciones
    ("los", None), ("dos", None), ("tus", None),             # 3 letras: solo exacta
    ("fibere", None),                                         # 6 letras: 2 ediciones es demasiado
    ("congetsoin", None) if False else ("xxxxxxxxxx", None),
    ("fiebre", None),                                         # exacta: no hay nada que corregir
])
def test_corregir_respeta_los_umbrales(palabra, esperada):
    assert lv.corregir(palabra, VOCAB) == esperada


def test_un_empate_entre_significados_distintos_no_se_corrige():
    vocab = {"pecho": {"dolor_pecho"}, "pesho": {"otro"}}                  # "pexho" está a distancia 1 de las dos
    assert lv.distancia("pexho", "pecho") == lv.distancia("pexho", "pesho") == 1
    assert lv.corregir("pexho", vocab) is None                              # ambiguo: es mejor preguntar que adivinar
    assert lv.corregir("pexho", {"pecho": {"dolor_pecho"}, "pechos": {"dolor_pecho"}}) == ("pecho", 1)   # mismo significado
    assert lv.corregir("pexho", {"pecho": {"dolor_pecho"}, "pesho": {"otro"}, "pexh": {"x"}}) is None


# ---------- en el extractor ----------
@pytest.mark.parametrize("texto, presentes, ausentes", [
    ("fievre", {"fiebre"}, set()),
    ("diarea", {"diarrea"}, set()),
    ("dolr de cabesa", {"dolor_cabeza"}, set()),
    ("me duele el peho", {"dolor_pecho"}, set()),
    ("no tengo fievre", set(), {"fiebre"}),
    ("no tengo fievre pero si tos", {"tos"}, {"fiebre"}),
    ("tengo vomitos y diarea", {"vomitos", "diarrea"}, set()),
])
def test_se_reconocen_los_errores_de_ortografia(texto, presentes, ausentes):
    e = kw.extraer(texto)
    assert e.presentes == presentes and e.ausentes == ausentes and e.correcciones


@pytest.mark.parametrize("palabra", ["los", "dos", "tus", "vos", "mos", "tas", "tes"])
def test_los_no_es_tos(palabra):
    assert kw.extraer(f"{palabra} amigos").presentes == set() and kw.extraer(palabra).correcciones == []


def test_la_traza_dice_que_se_corrigio():
    assert kw.extraer("tengo fievre").correcciones == ["Corregí 'fievre' → 'fiebre' (distancia 1)"]
    r = enviar(nueva(), "tengo fievre")
    assert "Corregí 'fievre' → 'fiebre' (distancia 1)" in r["traza"]
    assert any(l.startswith("Extractor") and "fiebre" in l for l in r["traza"])


def test_me_duele_el_peho_da_alarma_por_la_api():
    r = enviar(nueva(), "me duele el peho")
    assert r["urgencia"] == "urgencia_alta" and tiene_accion(r, "ubicacion")
    assert "Corregí 'peho' → 'pecho' (distancia 1)" in r["traza"]


def test_alarmas_mal_escritas_se_detectan():
    for texto in ["no puedo resprar", "dificultad para rrespirar", "tengo dolor de pecho"]:
        assert kw.extraer(texto).presentes & {"dificultad_respirar", "dolor_pecho"}, texto


# ---------- negadores y cortes: siempre exactos ----------
def test_un_negador_mal_escrito_no_niega():
    assert kw.extraer("tampoko fiebre").presentes == {"fiebre"}          # «tampoko» no es «tampoco»: no se aproxima
    assert kw.extraer("sinn fiebre").presentes == {"fiebre"}
    assert kw.extraer("nunka fiebre").presentes == {"fiebre"}


def test_un_corte_mal_escrito_no_corta_la_negacion():
    e = kw.extraer("no tengo fiebre pro tos")                            # «pro» no es «pero»: la negación sigue
    assert e.ausentes == {"fiebre", "tos"} and e.presentes == set()
    assert kw.extraer("no tengo fiebre pero tos").presentes == {"tos"}   # con el corte exacto sí corta


def test_los_negadores_y_cortes_nunca_son_destino_ni_origen_de_una_correccion():
    lex = kw.lexico()
    sagradas = set(lex["negadores"]) | set(lex["cortes"])
    assert not (sagradas & set(kw.destinos_de_correccion()))                # nunca se corrige HACIA un negador o corte
    for palabra in sorted(kw.protegidas()):
        assert kw.corregir_ortografia([palabra]) == ([palabra], [])         # y no se corrigen ellos mismos
    assert kw.extraer("nop tengo fiebre").correcciones == []                # «nop» tampoco se aproxima a «no»


# ---------- regresión: las claves que empiezan con un negador ----------
@pytest.mark.parametrize("texto, sintoma", [
    ("no puedo respirar", "dificultad_respirar"), ("no puedo respirar bien", "dificultad_respirar"),
    ("casi no puedo respirar", "dificultad_respirar"), ("no huelo nada", "perdida_olfato"),
    ("no siento sabores", "perdida_olfato"), ("casi no orina", "orina_poco"),
])
def test_las_claves_que_empiezan_con_no_se_detectan(texto, sintoma):
    """«no puedo respirar» no se detectaba nunca: el «no» se trataba como negador antes de emparejar la clave."""
    assert sintoma in kw.extraer(texto).presentes


def test_no_puedo_respirar_es_alarma_por_la_api():
    r = enviar(nueva(), "no puedo respirar")
    assert r["urgencia"] == "urgencia_alta" and tiene_accion(r, "ubicacion")


def test_los_negadores_normales_siguen_negando():
    assert kw.extraer("no tengo fiebre ni tos").ausentes == {"fiebre", "tos"}
    assert kw.extraer("no puedo respirar pero no tengo fiebre").presentes == {"dificultad_respirar"}
    assert kw.extraer("no puedo respirar pero no tengo fiebre").ausentes == {"fiebre"}


# ---------- falsos positivos ----------
@pytest.mark.parametrize("texto", [
    "hola buenas tardes quiero hacer una consulta por favor",
    "ya lo he hecho y me gusta el color del techo",
    "estamos locos de contentos con los resultados",
    "gracias doctor, mucho mejor ahora",
    "mi mama llamo hoy y dice que todo esta bien",
])
def test_frases_normales_no_generan_correcciones_ni_sintomas(texto):
    e = kw.extraer(texto)
    assert e.correcciones == [] and e.presentes == set() and e.ausentes == set()


def test_las_palabras_exactas_no_se_tocan():
    for palabra in kw.vocabulario():
        assert kw.corregir_ortografia([palabra]) == ([palabra], [])


def test_toda_correccion_queda_a_la_distancia_permitida():
    azar = random.Random(3)
    for palabra in [p for p in kw.vocabulario() if len(p) >= 5 and p not in kw.protegidas()]:
        i = azar.randrange(len(palabra))
        con_error = palabra[:i] + "x" + palabra[i + 1:]                  # una sustitución
        tokens, trazas = kw.corregir_ortografia([con_error])
        if trazas:
            corregida = tokens[0]
            assert lv.distancia(con_error, corregida) <= lv.umbral(max(len(con_error), len(corregida)))
