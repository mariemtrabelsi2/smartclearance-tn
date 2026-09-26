"""Construit donnees/smartclearance.db a partir des fichiers existants.

    py outils/migrer_vers_sqlite.py

Les CSV et le JSONL restent en place et ne sont jamais supprimes : ils sont la
source de la migration, et le backend csv reste utilisable a tout moment.
La base est construite dans un fichier temporaire puis mise en place d'un coup :
une migration interrompue ne laisse jamais une base a moitie remplie.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import stockage  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cible = stockage.BASE_SQLITE
    tmp = cible.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)

    # Memes lecteurs que le backend csv : les valeurs sont interpretees a l'identique.
    bareme = stockage._csv_lire_bareme() or []
    histo_brut = []
    if stockage.HISTORIQUE_CSV.exists():
        import csv
        with open(stockage.HISTORIQUE_CSV, newline="", encoding="utf-8") as f:
            histo_brut = list(csv.DictReader(f))   # valeur/poids gardes en texte, comme lus
    histo = stockage._csv_lire_historique() or []
    refs = []
    if stockage.REFERENCES_CSV.exists():
        import csv
        with open(stockage.REFERENCES_CSV, newline="", encoding="utf-8") as f:
            refs = list(csv.DictReader(f))
    feedback = stockage._csv_lire_feedback()
    nomenclature = stockage._csv_lire_nomenclature() or {}
    chapitres = stockage._csv_lire_chapitres() or {}

    con = stockage._connexion(tmp, creer=True)
    with con:
        con.executemany("INSERT INTO bareme VALUES (?, ?, ?, ?)",
                        [(l["code_sh"], l["pays_origine"], l["prix_kg_usd"], l["source"]) for l in bareme])
        con.executemany("INSERT INTO historique VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(b["importateur"], b["fournisseur"], b["code_sh"], b["pays_origine"],
                          h["date"].isoformat(), b["valeur"], b["poids"], h["prix_kg"])
                         for b, h in zip(histo_brut, histo)])
        con.executemany("INSERT OR IGNORE INTO references_vues VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [(stockage.cle_reference(l["reference_facture"]), l["reference_facture"],
                          l["numero_ddm"], stockage.cle_reference(l["numero_ddm"]),
                          l["importateur"], l["date"], l["date_analyse"]) for l in refs])
        con.executemany("INSERT INTO nomenclature_sh6 VALUES (?, ?, ?, ?)",
                        [(l["code_sh"], l["chapitre"], l["section"], l["designation"])
                         for l in nomenclature.values()])
        con.executemany("INSERT INTO chapitres_sh VALUES (?, ?, ?, ?, ?)",
                        [(l["chapitre"], l["section"], l["libelle_section"], l["libelle_court"],
                          l["designation"]) for l in chapitres.values()])
        import json
        con.executemany("INSERT INTO feedback (contenu) VALUES (?)",
                        [(json.dumps(e, ensure_ascii=False),) for e in feedback])
    comptes = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("bareme", "historique", "references_vues", "feedback",
                         "nomenclature_sh6", "chapitres_sh")}
    con.close()
    os.replace(tmp, cible)

    print(f"{cible} construite :")
    for t, n in comptes.items():
        print(f"  {t:16} {n} ligne(s)")
    attendus = {"bareme": len(bareme), "historique": len(histo),
                "nomenclature_sh6": len(nomenclature), "chapitres_sh": len(chapitres)}
    for t, n in attendus.items():
        if comptes[t] != n:
            print(f"  ECART : {t} a {comptes[t]} lignes, {n} attendues")
            sys.exit(1)
    print("Les fichiers CSV/JSONL d'origine sont conserves.")


if __name__ == "__main__":
    main()
