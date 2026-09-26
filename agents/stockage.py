"""Couche d'acces aux donnees. Aucun autre module ne sait d'ou viennent les
donnees : ils appellent ces fonctions, et le backend se choisit ici.

    SMARTCLEARANCE_STOCKAGE=csv     (defaut)  fichiers CSV / JSONL
    SMARTCLEARANCE_STOCKAGE=sqlite            donnees/smartclearance.db

Chaque fonction accepte une `source` facultative (chemin) : sans elle, la
source par defaut du backend actif ; avec elle, ce fichier-la (tests, registre
temporaire des mesures).
"""
import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BACKEND = os.environ.get("SMARTCLEARANCE_STOCKAGE", "csv").strip().lower()
if BACKEND not in ("csv", "sqlite"):
    raise ValueError(f"SMARTCLEARANCE_STOCKAGE inconnu : {BACKEND} (attendu : csv ou sqlite)")

BAREME_CSV = RACINE / "bareme.csv"
HISTORIQUE_CSV = RACINE / "donnees" / "historique.csv"
REFERENCES_CSV = RACINE / "donnees" / "references_vues.csv"
FEEDBACK_JSONL = RACINE / "feedback.jsonl"

COLONNES_REFERENCES = ["reference_facture", "numero_ddm", "importateur", "date", "date_analyse"]


def cle_reference(s):
    """Une reference se compare sans casse ni espaces parasites."""
    return " ".join(str(s or "").split()).upper()


def nom_source(jeu):
    """Libelle court de la source, pour les champs 'source' des alertes."""
    return {"bareme": BAREME_CSV.name, "historique": HISTORIQUE_CSV.name,
            "references": REFERENCES_CSV.name}[jeu]


# ============================================================ backend CSV

def _csv_lire_bareme(source=None):
    chemin = Path(source or BAREME_CSV)
    if not chemin.exists():
        return None
    lignes = []
    with open(chemin, newline="", encoding="utf-8") as f:
        for l in csv.DictReader(f):
            try:
                prix = float(l["prix_kg_usd"])
            except (TypeError, ValueError):
                continue
            lignes.append({"code_sh": l["code_sh"].strip(),
                           "pays_origine": l["pays_origine"].strip().upper(),
                           "prix_kg_usd": prix, "source": l.get("source")})
    return lignes


def _csv_chercher_bareme(code_sh, source=None):
    lignes = _csv_lire_bareme(source)
    return None if lignes is None else [l for l in lignes if l["code_sh"] == str(code_sh).strip()]


def _csv_lire_historique(source=None):
    chemin = Path(source or HISTORIQUE_CSV)
    if not chemin.exists():
        return None
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))
    for l in lignes:
        l["date"] = date.fromisoformat(str(l["date"])[:10])
        l["prix_kg"] = float(l["prix_kg"])
    return lignes


def _csv_chercher_reference(reference, source=None):
    chemin = Path(source or REFERENCES_CSV)
    if not chemin.exists():
        return None
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = [l for l in csv.DictReader(f)
                  if cle_reference(l["reference_facture"]) == cle_reference(reference)]
    return lignes or None


def _csv_ajouter_reference(ligne, chemin):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    nouveau = not chemin.exists()
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES_REFERENCES)
        if nouveau:
            w.writeheader()
        w.writerow(ligne)


def _csv_enregistrer_reference(reference, ddm, importateur, date_doc, source=None):
    """Idempotent : meme reference + meme DDM n'ajoute rien (reanalyse)."""
    deja = _csv_chercher_reference(reference, source) or []
    if any(cle_reference(l["numero_ddm"]) == cle_reference(ddm) for l in deja):
        return False
    _csv_ajouter_reference({"reference_facture": reference, "numero_ddm": ddm,
                            "importateur": importateur, "date": date_doc or "",
                            "date_analyse": date.today().isoformat()},
                           source or REFERENCES_CSV)
    return True


def _jsonl_ajouter(entree, chemin):
    with open(chemin, "a", encoding="utf-8") as f:
        f.write(json.dumps(entree, ensure_ascii=False) + "\n")


def _csv_enregistrer_feedback(entree, source=None):
    _jsonl_ajouter(entree, source or FEEDBACK_JSONL)


def _csv_lire_feedback(source=None):
    chemin = Path(source or FEEDBACK_JSONL)
    if not chemin.exists():
        return []
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _csv_registre_temporaire():
    return Path(tempfile.mkdtemp(prefix="registre_mesure_")) / "references_vues.csv"


# ============================================================ interface publique

_IMPL = {
    "csv": {"lire_bareme": _csv_lire_bareme, "chercher_bareme": _csv_chercher_bareme,
            "lire_historique": _csv_lire_historique,
            "chercher_reference": _csv_chercher_reference,
            "enregistrer_reference": _csv_enregistrer_reference,
            "enregistrer_feedback": _csv_enregistrer_feedback,
            "lire_feedback": _csv_lire_feedback,
            "registre_temporaire": _csv_registre_temporaire},
}


def _impl(nom):
    if BACKEND not in _IMPL:
        raise NotImplementedError(f"backend {BACKEND} non disponible")
    return _IMPL[BACKEND][nom]


def lire_bareme(source=None):
    """-> [{code_sh, pays_origine, prix_kg_usd, source}] ou None si indisponible."""
    return _impl("lire_bareme")(source)


def chercher_bareme(code_sh, source=None):
    """Lignes du bareme pour un code SH (toutes origines) ou None si indisponible."""
    return _impl("chercher_bareme")(code_sh, source)


def lire_historique(source=None):
    """-> lignes avec date (datetime.date) et prix_kg (float), ou None."""
    return _impl("lire_historique")(source)


def chercher_reference(reference, source=None):
    """Declarations deja vues avec cette reference de facture, ou None."""
    return _impl("chercher_reference")(reference, source)


def enregistrer_reference(reference, ddm, importateur, date_doc, source=None):
    """-> True si ajoutee, False si deja presente (meme reference, meme DDM)."""
    return _impl("enregistrer_reference")(reference, ddm, importateur, date_doc, source)


def enregistrer_feedback(entree, source=None):
    _impl("enregistrer_feedback")(entree, source)


def lire_feedback(source=None):
    return _impl("lire_feedback")(source)


def registre_temporaire():
    """Registre vide, propre a une mesure : une mesure ne doit jamais heriter des
    references d'une execution precedente."""
    return _impl("registre_temporaire")()
