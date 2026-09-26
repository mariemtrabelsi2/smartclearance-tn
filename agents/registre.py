"""Registre des references de facture deja vues : une meme facture ne doit
couvrir qu'une seule declaration.

Le fichier s'accumule d'une analyse a l'autre : c'est voulu en exploitation,
mais une mesure doit partir d'un registre vide (voir evaluer.py), sinon la
deuxieme execution alerterait sur tous les dossiers.
"""
import csv
from datetime import date
from pathlib import Path

from agents.base import RapportAgent, NIVEAU_CONTRADICTION

RACINE = Path(__file__).resolve().parent.parent
REGISTRE_DEFAUT = RACINE / "donnees" / "references_vues.csv"
COLONNES = ["reference_facture", "numero_ddm", "importateur", "date", "date_analyse"]


def _cle(s):
    return " ".join(str(s or "").split()).upper()


def lire(registre_csv):
    if not Path(registre_csv).exists():
        return []
    with open(registre_csv, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def analyser(ddm: dict, facture: dict, registre_csv=REGISTRE_DEFAUT) -> RapportAgent:
    r = RapportAgent(agent="Registre des references")
    # La reference lue sur la facture fait foi ; a defaut, celle declaree en DDM.
    ref = (facture or {}).get("reference") or ddm.get("reference_facture")
    numero = ddm.get("numero_ddm")
    if not ref or not numero:
        r.non_lus.append("reference facture ou numero DDM absent : doublon non verifie")
        r.statut = "INCOMPLET"
        return r

    lignes = lire(registre_csv)
    memes = [l for l in lignes if _cle(l["reference_facture"]) == _cle(ref)]
    autres = sorted((l for l in memes if _cle(l["numero_ddm"]) != _cle(numero)),
                    key=lambda l: l["date_analyse"])
    if autres:
        p = autres[0]
        r.ajouter(
            type="reference_facture_dupliquee", niveau=NIVEAU_CONTRADICTION, gravite=85,
            message="Cette reference de facture couvre deja une autre declaration.",
            preuve={"reference": ref, "ddm_actuelle": numero, "ddm_precedente": p["numero_ddm"],
                    "date_precedente": p["date"], "importateur_precedent": p["importateur"],
                    "nb_declarations_avec_cette_reference": len({_cle(l["numero_ddm"]) for l in memes}) + 1},
            source=f"registre {Path(registre_csv).name} / facture : ligne 'Ref'",
        )

    # Meme reference + meme DDM : simple reanalyse, rien a ajouter ni a signaler.
    if not any(_cle(l["numero_ddm"]) == _cle(numero) for l in memes):
        Path(registre_csv).parent.mkdir(parents=True, exist_ok=True)
        nouveau = not Path(registre_csv).exists()
        with open(registre_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLONNES)
            if nouveau:
                w.writeheader()
            w.writerow({"reference_facture": ref, "numero_ddm": numero,
                        "importateur": ddm.get("importateur"),
                        "date": (facture or {}).get("date") or "",
                        "date_analyse": date.today().isoformat()})
    return r
