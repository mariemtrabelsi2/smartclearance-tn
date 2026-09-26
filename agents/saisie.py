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


def controles_saisie(ddm, docs, details, date_reference):
    """-> liste de (message, preuve, source) pour les saisies douteuses.
    Rien n'est corrige : chaque preuve montre la valeur telle qu'elle a ete lue."""
    from datetime import date
    constats = []

    # 1. Numeros de conteneur (ISO 6346), regroupes par numero.
    vus = {}
    for doc, num in (("colisage", docs["colisage"].get("conteneur")),
                     ("connaissement", docs["transport"].get("conteneur")),
                     ("DDM", ddm.get("conteneur"))):
        if num:
            vus.setdefault(re.sub(r"[\s\-]", "", str(num)).upper(), []).append(doc)
    for num, ou in vus.items():
        defaut = verifier_conteneur(num)
        if defaut:
            constats.append((f"Numero de conteneur {num} non conforme a la norme ISO 6346 "
                             f"({defaut['motif']}) : erreur de saisie possible.",
                             {**defaut, "documents": ou},
                             "numero de conteneur : " + " / ".join(ou)))

    # 2. Dates : facture apres le certificat, ou date posterieure a l'analyse.
    def lire_date(s):
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return None
    d_fac = lire_date(docs["facture"].get("date"))
    d_cer = lire_date((docs.get("certificat") or {}).get("date_emission"))
    if d_fac and d_cer and d_fac > d_cer:
        constats.append((f"La facture ({d_fac}) est datee apres le certificat d'origine ({d_cer}) "
                         f"qui s'y rapporte.",
                         {"date_facture": d_fac.isoformat(), "date_certificat": d_cer.isoformat(),
                          "motif": "facture posterieure au certificat"},
                         "facture : ligne 'Date' / certificat : ligne 'Date of issue'"))
    for nom, d in (("facture", d_fac), ("certificat d'origine", d_cer)):
        if d and d > date_reference:
            constats.append((f"Date du document '{nom}' ({d}) posterieure a la date d'analyse "
                             f"({date_reference}).",
                             {"document": nom, "date_lue": d.isoformat(),
                              "date_analyse": date_reference.isoformat(), "motif": "date dans le futur"},
                             f"{nom} : date"))

    # 3. Lettre a la place d'un chiffre : on propose, on ne substitue pas.
    for doc, champs in details.items():
        for champ, d in champs.items():
            if d.get("lecture_alternative") is not None:
                constats.append((f"Valeur '{d['brut']}' illisible comme nombre ({doc}, {champ}) : "
                                 f"confusion de caracteres probable. Lecture alternative proposee "
                                 f"{d['lecture_alternative']}, NON substituee.",
                                 {"document": doc, "champ": champ, "brut": d["brut"],
                                  "lecture_alternative": d["lecture_alternative"],
                                  "motif": "confusion de caracteres probable (O/0, l/1, I/1, S/5)"},
                                 f"{doc} : champ {champ}"))
    return constats


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
