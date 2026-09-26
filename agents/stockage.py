"""Couche d'acces aux donnees. Aucun autre module ne sait d'ou viennent les
donnees : ils appellent ces fonctions, et le backend se choisit ici.

    SMARTCLEARANCE_STOCKAGE=csv     (defaut)  fichiers CSV / JSONL
    SMARTCLEARANCE_STOCKAGE=sqlite            donnees/smartclearance.db

Chaque fonction accepte une `source` facultative (chemin) : sans elle, la
source par defaut du backend actif ; avec elle, ce fichier-la (tests, registre
temporaire des mesures).
"""
import csv
from contextlib import closing
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
NOMENCLATURE_CSV = RACINE / "donnees" / "nomenclature_sh6.csv"
CHAPITRES_CSV = RACINE / "donnees" / "chapitres_sh.csv"

COLONNES_REFERENCES = ["reference_facture", "numero_ddm", "importateur", "date", "date_analyse"]


def cle_reference(s):
    """Une reference se compare sans casse ni espaces parasites."""
    return " ".join(str(s or "").split()).upper()


def nom_source(jeu):
    """Libelle court de la source, pour les champs 'source' des alertes."""
    if BACKEND == "sqlite":
        return f"{BASE_SQLITE.name}:{ {'references': 'references_vues'}.get(jeu, jeu) }"
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


def _csv_lire_nomenclature(source=None):
    chemin = Path(source or NOMENCLATURE_CSV)
    if not chemin.exists():
        return None
    with open(chemin, newline="", encoding="utf-8") as f:
        return {l["code_sh"]: l for l in csv.DictReader(f)}


def _csv_lire_chapitres(source=None):
    chemin = Path(source or CHAPITRES_CSV)
    if not chemin.exists():
        return None
    with open(chemin, newline="", encoding="utf-8") as f:
        return {l["chapitre"]: l for l in csv.DictReader(f)}


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


# ============================================================ backend SQLite
#
# Ce que SQLite apporte ici : l'atomicite des ecritures du registre (deux
# analyses simultanees ne corrompent pas le fichier, et la contrainte UNIQUE
# empeche d'enregistrer deux fois la meme declaration), une requete indexee
# sur le bareme, un format unique pour les quatre jeux. PAS de gain de vitesse
# sur quelques milliers de lignes.

BASE_SQLITE = RACINE / "donnees" / "smartclearance.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS bareme (
    code_sh TEXT NOT NULL, pays_origine TEXT NOT NULL,
    prix_kg_usd REAL NOT NULL, source TEXT);
CREATE INDEX IF NOT EXISTS idx_bareme_sh_pays ON bareme(code_sh, pays_origine);
CREATE TABLE IF NOT EXISTS historique (
    importateur TEXT, fournisseur TEXT, code_sh TEXT, pays_origine TEXT,
    date TEXT, valeur TEXT, poids TEXT, prix_kg REAL);
CREATE TABLE IF NOT EXISTS references_vues (
    reference TEXT NOT NULL,          -- cle normalisee (casse, espaces)
    reference_facture TEXT NOT NULL,  -- telle que lue
    numero_ddm TEXT NOT NULL, numero_ddm_cle TEXT NOT NULL,
    importateur TEXT, date TEXT, date_analyse TEXT,
    UNIQUE (reference, numero_ddm_cle));
CREATE INDEX IF NOT EXISTS idx_references ON references_vues(reference);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, contenu TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nomenclature_sh6 (
    code_sh TEXT PRIMARY KEY, chapitre TEXT, section TEXT, designation TEXT);
CREATE TABLE IF NOT EXISTS chapitres_sh (
    chapitre TEXT PRIMARY KEY, section TEXT, libelle_section TEXT,
    libelle_court TEXT, designation TEXT);
"""


def _connexion(chemin, creer=False):
    import sqlite3
    chemin = Path(chemin)
    if not chemin.exists() and not creer:
        raise FileNotFoundError(f"{chemin} absent : lancer py outils/migrer_vers_sqlite.py "
                                f"ou revenir a SMARTCLEARANCE_STOCKAGE=csv")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(chemin, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _sql_lire_bareme(source=None):
    with closing(_connexion(source or BASE_SQLITE)) as con:
        return [dict(l) for l in con.execute(
            "SELECT code_sh, pays_origine, prix_kg_usd, source FROM bareme ORDER BY rowid")]


def _sql_chercher_bareme(code_sh, source=None):
    # Requete sur l'index (code_sh, pays_origine) : pas de parcours du bareme.
    with closing(_connexion(source or BASE_SQLITE)) as con:
        return [dict(l) for l in con.execute(
            "SELECT code_sh, pays_origine, prix_kg_usd, source FROM bareme "
            "WHERE code_sh = ? ORDER BY rowid", (str(code_sh).strip(),))]


def _sql_lire_historique(source=None):
    # ORDER BY rowid : meme ordre que le CSV, dont depend la foret d'isolation.
    with closing(_connexion(source or BASE_SQLITE)) as con:
        lignes = [dict(l) for l in con.execute(
            "SELECT importateur, fournisseur, code_sh, pays_origine, date, valeur, poids, "
            "prix_kg FROM historique ORDER BY rowid")]
    for l in lignes:
        l["date"] = date.fromisoformat(l["date"])
    return lignes or None


def _export_references(source):
    """Export CSV tenu a jour meme en mode sqlite : un auditeur doit pouvoir
    ouvrir le registre sans outil."""
    return REFERENCES_CSV if source is None else Path(source).with_suffix(".csv")


def _sql_chercher_reference(reference, source=None):
    with closing(_connexion(source or BASE_SQLITE, creer=True)) as con:
        lignes = [dict(l) for l in con.execute(
            "SELECT reference_facture, numero_ddm, importateur, date, date_analyse "
            "FROM references_vues WHERE reference = ? ORDER BY rowid",
            (cle_reference(reference),))]
    return lignes or None


def _sql_enregistrer_reference(reference, ddm, importateur, date_doc, source=None):
    ligne = {"reference_facture": reference, "numero_ddm": ddm, "importateur": importateur,
             "date": date_doc or "", "date_analyse": date.today().isoformat()}
    con = _connexion(source or BASE_SQLITE, creer=True)
    try:
        with con:   # transaction : tout ou rien
            cur = con.execute(
                "INSERT OR IGNORE INTO references_vues (reference, reference_facture, numero_ddm, "
                "numero_ddm_cle, importateur, date, date_analyse) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cle_reference(reference), reference, ddm, cle_reference(ddm),
                 importateur, ligne["date"], ligne["date_analyse"]))
    finally:
        con.close()
    if cur.rowcount == 1:
        _csv_ajouter_reference(ligne, _export_references(source))
        return True
    return False


def _sql_enregistrer_feedback(entree, source=None):
    con = _connexion(source or BASE_SQLITE, creer=True)
    try:
        with con:
            con.execute("INSERT INTO feedback (contenu) VALUES (?)",
                        (json.dumps(entree, ensure_ascii=False),))
    finally:
        con.close()
    # Export lisible sans outil, comme le registre.
    _jsonl_ajouter(entree, FEEDBACK_JSONL if source is None else Path(source).with_suffix(".jsonl"))


def _sql_lire_feedback(source=None):
    with closing(_connexion(source or BASE_SQLITE, creer=True)) as con:
        return [json.loads(l["contenu"]) for l in con.execute("SELECT contenu FROM feedback ORDER BY id")]


def _sql_lire_nomenclature(source=None):
    with closing(_connexion(source or BASE_SQLITE)) as con:
        lignes = {l["code_sh"]: dict(l) for l in con.execute("SELECT * FROM nomenclature_sh6")}
    return lignes or None


def _sql_lire_chapitres(source=None):
    with closing(_connexion(source or BASE_SQLITE)) as con:
        lignes = {l["chapitre"]: dict(l) for l in con.execute("SELECT * FROM chapitres_sh")}
    return lignes or None


def _sql_registre_temporaire():
    return Path(tempfile.mkdtemp(prefix="registre_mesure_")) / "registre.db"


# ============================================================ interface publique

_IMPL = {
    "csv": {"lire_bareme": _csv_lire_bareme, "chercher_bareme": _csv_chercher_bareme,
            "lire_historique": _csv_lire_historique,
            "chercher_reference": _csv_chercher_reference,
            "enregistrer_reference": _csv_enregistrer_reference,
            "enregistrer_feedback": _csv_enregistrer_feedback,
            "lire_feedback": _csv_lire_feedback,
            "registre_temporaire": _csv_registre_temporaire,
            "lire_nomenclature": _csv_lire_nomenclature, "lire_chapitres": _csv_lire_chapitres},
    "sqlite": {"lire_bareme": _sql_lire_bareme, "chercher_bareme": _sql_chercher_bareme,
               "lire_historique": _sql_lire_historique,
               "chercher_reference": _sql_chercher_reference,
               "enregistrer_reference": _sql_enregistrer_reference,
               "enregistrer_feedback": _sql_enregistrer_feedback,
               "lire_feedback": _sql_lire_feedback,
               "registre_temporaire": _sql_registre_temporaire,
               "lire_nomenclature": _sql_lire_nomenclature, "lire_chapitres": _sql_lire_chapitres},
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


def lire_nomenclature(source=None):
    """{code_sh: {code_sh, chapitre, section, designation}} (SH 2022, 6 chiffres) ou None."""
    return _impl("lire_nomenclature")(source)


def lire_chapitres(source=None):
    """{chapitre: {chapitre, section, libelle_section, libelle_court, designation}} ou None."""
    return _impl("lire_chapitres")(source)


def registre_temporaire():
    """Registre vide, propre a une mesure : une mesure ne doit jamais heriter des
    references d'une execution precedente."""
    return _impl("registre_temporaire")()
