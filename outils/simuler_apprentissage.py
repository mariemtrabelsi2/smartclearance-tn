"""RETOURS SYNTHETIQUES - demonstration du mecanisme, ces decisions n'ont ete
prises par aucun inspecteur.

    py outils/simuler_apprentissage.py

Montre le scenario Jour 1 / Jour 15 / Jour 30 sur un meme dossier (graine 99,
dossier 04, dont l'alerte de prix porte un justificatif de remise coherent).
Le feedback simule est ecrit dans donnees/simulation/, JAMAIS dans le feedback
reel : le script refuse d'ecrire hors de ce dossier.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import apprentissage, stockage  # noqa: E402
from agents.orchestrateur import analyser_dossier  # noqa: E402

AVERTISSEMENT = ("RETOURS SYNTHETIQUES - demonstration du mecanisme, ces decisions "
                 "n'ont ete prises par aucun inspecteur.")
RACINE = Path(__file__).resolve().parent.parent
DOSSIER_SIMULATION = RACINE / "donnees" / "simulation"
FEEDBACK_SIMULE = DOSSIER_SIMULATION / "feedback_simule.jsonl"
DOSSIER_DEMO = "dossiers_graine99/dossier_04"
MOTIF_DEMO = ("sous_evaluation_justifiee", True, "moyenne")


def _verifier_cible(chemin):
    """Garde-fou : aucune ecriture hors de donnees/simulation/, et jamais dans
    le feedback reel ni dans les ajustements reels."""
    chemin = Path(chemin).resolve()
    interdits = {stockage.FEEDBACK_JSONL.resolve(), apprentissage.AJUSTEMENTS_DEFAUT.resolve()}
    if chemin in interdits or DOSSIER_SIMULATION.resolve() not in chemin.parents:
        raise PermissionError(f"ecriture refusee hors de {DOSSIER_SIMULATION} : {chemin}")
    return chemin


def retour(type_alerte, niveau, decision, justificatif=None, fiabilite=None):
    preuve = {}
    if justificatif:
        preuve["justificatif"] = justificatif
    if fiabilite:
        preuve["fiabilite_reference"] = fiabilite
    return {"synthetique": True, "avertissement": AVERTISSEMENT, "dossier": "SIMULATION",
            "type_alerte": type_alerte, "niveau": niveau, "preuve": preuve,
            "decision_inspecteur": decision}


def lot(n, confirmes):
    """n retours sur le motif de demonstration, dont `confirmes` confirmations."""
    return [retour(MOTIF_DEMO[0], 2,
                   apprentissage.CONFIRME if i < confirmes else apprentissage.JUSTIFIE,
                   justificatif="COMMERCIAL AGREEMENT", fiabilite=MOTIF_DEMO[2])
            for i in range(n)]


def ecrire(retours, jour):
    DOSSIER_SIMULATION.mkdir(parents=True, exist_ok=True)
    fb = _verifier_cible(FEEDBACK_SIMULE)
    with open(fb, "w", encoding="utf-8") as f:
        f.write(json.dumps({"entete": AVERTISSEMENT}, ensure_ascii=False) + "\n")
        for r in retours:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ajust = _verifier_cible(DOSSIER_SIMULATION / f"ajustements_jour{jour:02d}.json")
    donnees = apprentissage.calculer(retours)
    donnees.update({"avertissement": AVERTISSEMENT, "source_feedback": str(fb)})
    ajust.write_text(json.dumps(donnees, indent=2, ensure_ascii=False), encoding="utf-8")
    return ajust, donnees


def analyser(ajustements, contexte_mesure=False):
    """Par defaut, le dossier seul (comme a sa premiere ouverture dans l'interface).
    contexte_mesure=True : dossiers precedents du jeu vus avant, comme evaluer.py ;
    le dossier y porte alors un doublon de facture (niveau 1)."""
    if not contexte_mesure:
        return analyser_dossier(DOSSIER_DEMO, registre=False, rediger=False, ajustements=ajustements)
    reg = stockage.registre_temporaire()
    for i in (1, 2, 3):
        analyser_dossier(f"dossiers_graine99/dossier_0{i}", registre=reg, rediger=False,
                         ajustements=ajustements)
    return analyser_dossier(DOSSIER_DEMO, registre=reg, rediger=False, ajustements=ajustements)


def afficher(titre, s):
    print(f"\n=== {titre} : score {s['score']}/100, {s['recommandation']}")
    for a in s["alertes"]:
        p = a["preuve"]
        note = ""
        if "ajustement_apprentissage" in p:
            note = (f"  <- x{p['ajustement_apprentissage']} ({p['gravite_avant_ajustement']} -> "
                    f"{a['gravite']}), fonde sur {p['fonde_sur']}")
        elif "retours_inspecteurs" in p:
            note = f"  <- compteur seul : {p['retours_inspecteurs']}"
        print(f"   niveau {a['niveau']}  {a['type']:40} gravite {a['gravite']:>3}{note}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(AVERTISSEMENT)
    print("=" * len(AVERTISSEMENT))

    # Garde-fous montres dans la meme simulation : 25 retours sur une alerte de
    # niveau 1 (jamais appris) et 9 retours sur un autre motif (sous le seuil).
    temoins = ([retour("reference_facture_dupliquee", 1, apprentissage.JUSTIFIE)] * 25
               + [retour("designation_vs_sh", 2, apprentissage.JUSTIFIE)] * 9)

    afficher("Jour 1  (aucun retour)", analyser(DOSSIER_SIMULATION / "absent.json"))

    j15 = lot(14, 4) + temoins
    f15, d15 = ecrire(j15, 15)
    afficher("Jour 15 (14 retours dont 4 confirmations)", analyser(f15))

    j30 = lot(14, 4) + lot(26, 2) + temoins        # cumul : 40 retours, 6 confirmations
    f30, d30 = ecrire(j30, 30)
    afficher("Jour 30 (40 retours dont 6 confirmations)", analyser(f30))

    print("\n--- Meme dossier dans le contexte de la mesure (doublon de facture, niveau 1) :")
    afficher("Jour 1 ", analyser(DOSSIER_SIMULATION / "absent.json", contexte_mesure=True))
    afficher("Jour 30", analyser(f30, contexte_mesure=True))
    print("   -> score inchange : il est porte par une contradiction de niveau 1, que "
          "l'apprentissage ne touche jamais.")

    print(f"\nRetours de niveau 1 ignores : {d30['retours_niveau1_ignores']} "
          "(une contradiction n'est jamais apprise)")
    print(f"Fichiers : {FEEDBACK_SIMULE}, {f15.name}, {f30.name} (dans {DOSSIER_SIMULATION})")
    print(AVERTISSEMENT)


if __name__ == "__main__":
    main()
