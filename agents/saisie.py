"""Controles de saisie : on SIGNALE une valeur douteuse, on ne la corrige jamais.

La declaration est un acte juridique ; proposer une lecture alternative est
utile, la substituer fausserait la piece sur laquelle l'inspecteur decide.
"""
import re
import string

# ISO 6346 : A=10, puis on saute les multiples de 11 (11, 22, 33).
_VALEURS = {}
_v = 10
for _l in string.ascii_uppercase:
    if _v % 11 == 0:
        _v += 1
    _VALEURS[_l] = _v
    _v += 1


def chiffre_controle_iso6346(dix_premiers):
    """Chiffre de controle attendu pour les 10 premiers caracteres (4 lettres +
    6 chiffres) : somme des valeurs ponderees par 2^i, modulo 11, 10 -> 0."""
    total = 0
    for i, c in enumerate(dix_premiers):
        total += (_VALEURS[c] if c.isalpha() else int(c)) * (2 ** i)
    return total % 11 % 10


def verifier_conteneur(numero):
    """-> None si valide, sinon dict de preuve (format invalide ou chiffre faux)."""
    if not numero:
        return None
    n = re.sub(r"[\s\-]", "", str(numero)).upper()
    if not re.fullmatch(r"[A-Z]{4}\d{7}", n):
        return {"conteneur": numero, "motif": "format ISO 6346 non respecte (4 lettres + 7 chiffres)"}
    attendu, lu = chiffre_controle_iso6346(n[:10]), int(n[10])
    if attendu != lu:
        return {"conteneur": numero, "chiffre_attendu": attendu, "chiffre_lu": lu,
                "motif": "chiffre de controle ISO 6346 faux"}
    return None
