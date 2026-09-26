"""Pre-genere les explications des 60 dossiers de test dans donnees/explications.json.

    py outils/pregenerer_explications.py [--pause SECONDES]

--pause espace les appels (offre gratuite Gemini : limite de requetes par
minute, HTTP 429). Ce n'est pas un nouvel essai : chaque dossier a toujours
une seule tentative de 5 s ; relancer le script ne rappelle que les dossiers
absents du cache.

C'est le SEUL endroit qui appelle le modele de langage. L'interface lit ensuite
le cache et ne fait aucun appel reseau : une coupure pendant la demonstration
ne change rien a l'ecran. Sans cle API, le script le dit et rien n'est ecrit.
"""
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")   # avant numpy
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import redaction, stockage  # noqa: E402
from agents.orchestrateur import analyser_dossier  # noqa: E402

JEUX = ["dossiers", "dossiers_graine99", "dossiers_graine123"]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    racine = Path(__file__).resolve().parent.parent
    pause = float(sys.argv[sys.argv.index("--pause") + 1]) if "--pause" in sys.argv else 0.0
    cache = redaction.lire_cache()
    sources, motifs, durees, durees_ok = Counter(), Counter(), [], []
    if not redaction.cle_api():
        print("Aucune cle API (GEMINI_API_KEY ou ANTHROPIC_API_KEY dans .env) : "
              "tout passera par le repli.")
    else:
        print(f"Fournisseur : {redaction.fournisseur()} | modele : {redaction.modele()}")

    for jeu in JEUX:
        # Registre vide par jeu, comme la mesure : les syntheses (et donc les cles
        # du cache) sont celles que produit evaluer.py.
        registre = stockage.registre_temporaire()
        for d in sorted((racine / jeu).glob("dossier_*")):
            s = analyser_dossier(d, registre=registre, rediger=False)
            texte, source, detail = redaction.rediger_explication(s, autoriser_reseau=True, cache=cache)
            sources[source] += 1
            if "duree_s" in detail:            # un appel reseau a eu lieu
                durees.append(detail["duree_s"])
                if source == "llm":
                    durees_ok.append(detail["duree_s"])
                time.sleep(pause)
            if source == "deterministe":
                motifs[detail["motif"]] += 1
            print(f"{jeu}/{d.name} : {source}" + (f" ({detail['motif']})" if source != "llm" else ""))

    redaction.ecrire_cache(cache)
    print(f"\nLLM : {sources['llm']} | repli deterministe : {sources['deterministe']}")
    for motif, n in motifs.most_common():
        print(f"  {n:>3} x {motif}")
    if durees:
        print(f"Temps d'un appel (tous) : median {statistics.median(durees):.2f} s, "
              f"max {max(durees):.2f} s ({len(durees)} appels)")
    if durees_ok:
        print(f"Temps d'un appel reussi : median {statistics.median(durees_ok):.2f} s, "
              f"max {max(durees_ok):.2f} s ({len(durees_ok)} appels)")
    print(f"Deja en cache avant ce passage : {sources['llm'] - len(durees_ok)}")
    print(f"Rejets detailles : {redaction.JOURNAL_REJETS}")
    print(f"Cache : {redaction.CACHE} ({len(cache)} entree(s))")


if __name__ == "__main__":
    main()
