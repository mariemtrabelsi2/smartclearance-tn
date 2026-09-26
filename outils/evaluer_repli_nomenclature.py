"""Evaluation du NIVEAU 2 (non livre) : designation_vs_sh etendu aux 5612 positions
de la nomenclature, en REPLI quand le produit n'est pas dans la table prioritaire.

    py outils/evaluer_repli_nomenclature.py

Le repli n'est PAS branche dans l'Agent 1 : ce script mesure s'il le merite.
1. Sur les 3 graines : combien de fois le repli serait-il appele ?
2. Sur des designations HORS table (cas construits, codes SH 2022 attribues a la
   main) : faux positifs sur les bons codes, detection sur des codes errones.
"""
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import nomenclature  # noqa: E402
from agents.inspecteur_documentaire import _produit  # noqa: E402
from agents.extraction import pdf_vers_texte, extraire_champs  # noqa: E402

VIDES = {"and", "or", "of", "the", "for", "with", "not", "other", "nec", "whether", "in",
         "heading", "chapter", "their", "parts", "thereof", "than", "including", "excluding",
         "incorporating", "containing", "having", "put", "up", "no", "which", "such", "being"}
SEUIL = 0.5          # part des mots de la designation retrouves dans le libelle officiel


def mots(s):
    return {m.rstrip("s") for m in re.findall(r"[a-z]+", s.lower()) if len(m) > 2 and m not in VIDES}


def candidats(designation, k=5):
    t = mots(designation)
    if not t:
        return []
    scores = []
    for code, pos in (nomenclature._positions("csv") or {}).items():
        commun = len(t & mots(pos["designation"]))
        if commun:
            scores.append((commun / len(t), code))
    return [(round(sc, 2), c) for sc, c in sorted(scores, reverse=True)[:k] if sc >= SEUIL]


def verdict(designation, code_declare):
    """'alerte' / 'coherent' / 'indetermine' (aucun libelle assez proche)."""
    c = candidats(designation)
    if not c:
        return "indetermine", c
    if any(code[:4] == str(code_declare)[:4] for _, code in c):
        return "coherent", c
    return "alerte", c


# Designations commerciales hors table, avec leur code SH 2022 (attribution manuelle).
CAS = [
    ("Laptop computer 15.6 inch", "847130"),
    ("Green coffee beans Arabica, not roasted", "090111"),
    ("Paracetamol 500mg tablets, packaged for retail sale", "300490"),
    ("Galvanized steel sheet, zinc coated", "721049"),
    ("Men's leather shoes, rubber soles", "640399"),
    ("Portland cement, grey", "252329"),
    ("Fresh tomatoes", "070200"),
    ("Frozen shrimp", "030617"),
    ("Swivel office chairs, height adjustable", "940139"),   # 940130 (SH 2017) scinde en 2022
    ("Fresh dates", "080410"),
    ("Mineral water, not sweetened", "220110"),
    ("Cotton bed sheets", "630231"),
    ("New pneumatic rubber tyres for passenger cars", "401110"),
    ("Household refrigerator-freezer combined", "841810"),
]
FAUX_CODE = "732690"   # "Iron or steel; articles n.e.c." : faux pour toutes les lignes ci-dessus


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    appels = 0
    for d in sorted(glob.glob("dossiers*/dossier_*")):
        des = extraire_champs(pdf_vers_texte(Path(d) / "facture.pdf"), "facture")["designation"]
        appels += _produit(des) is None
    print(f"1. Sur les 60 dossiers des 3 graines, le repli serait appele {appels} fois "
          "(toutes les designations sont dans la table prioritaire).")

    print("\n2. Designations hors table, CODE CORRECT (toute alerte = faux positif) :")
    fp = ind = 0
    for des, code in CAS:
        v, c = verdict(des, code)
        fp += v == "alerte"; ind += v == "indetermine"
        print(f"   {v:12} {code}  {des:48} meilleurs : {c[:2]}")
    print(f"   -> faux positifs : {fp}/{len(CAS)} | sans avis : {ind}/{len(CAS)}")

    print(f"\n3. Memes designations, CODE ERRONE {FAUX_CODE} (alerte attendue) :")
    det = sum(verdict(des, FAUX_CODE)[0] == "alerte" for des, _ in CAS)
    print(f"   -> detectees : {det}/{len(CAS)}")


if __name__ == "__main__":
    main()
