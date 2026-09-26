"""Nomenclature SH 2022 a 6 chiffres (5613 positions) : existence d'un code,
designation officielle, libelles de chapitres.

Source : donnees ouvertes (voir donnees/nomenclature_source.txt), descriptions
en anglais. Nomenclature absente : chaque fonction renvoie None, et l'appelant
le signale au lieu de conclure.
"""
import re
from functools import lru_cache

from agents import stockage

LIBELLE_SOURCE = "nomenclature SH 2022"


@lru_cache(maxsize=2)
def _positions(backend):
    return stockage.lire_nomenclature()


@lru_cache(maxsize=2)
def _chapitres(backend):
    return stockage.lire_chapitres()


def disponible():
    return bool(_positions(stockage.BACKEND))


def nb_positions():
    return len(_positions(stockage.BACKEND) or {})


def normaliser(code):
    return re.sub(r"\D", "", str(code or ""))


def existe(code):
    """True / False, ou None si la nomenclature n'est pas disponible."""
    positions = _positions(stockage.BACKEND)
    if not positions:
        return None
    return normaliser(code) in positions


def designation(code):
    p = (_positions(stockage.BACKEND) or {}).get(normaliser(code))
    return p["designation"] if p else None


def libelle_chapitre(chapitre):
    c = (_chapitres(stockage.BACKEND) or {}).get(str(chapitre).zfill(2))
    return c["libelle_court"] if c else None


def chapitre_lisible(chapitre):
    """'85' -> '85 (Electrical machinery and equipment and parts thereof)'."""
    lib = libelle_chapitre(chapitre)
    return f"{chapitre} ({lib})" if lib else str(chapitre)


def code_lisible(code):
    """'852872' -> "852872 (Reception apparatus for television...)"."""
    d = designation(code)
    return f"{code} ({d})" if d else str(code)
