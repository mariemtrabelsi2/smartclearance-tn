"""Recalcule donnees/ajustements.json a partir des retours des inspecteurs.

    py outils/recalculer_ajustements.py

Lit le feedback reel (feedback.jsonl ou table feedback). Chaque motif affiche
ses compteurs ; un facteur n'est actif qu'a partir de 10 retours, jamais sur
une alerte de niveau 1. Pour revenir en arriere : outils/reinitialiser_apprentissage.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import apprentissage  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = apprentissage.recalculer()
    print(f"{apprentissage.AJUSTEMENTS_DEFAUT} ecrit le {d['calcule_le']}")
    print(f"{d['nb_retours_lus']} retour(s) lu(s), {d['retours_niveau1_ignores']} sur des alertes "
          f"de niveau 1 (jamais appris)")
    for k, m in d["motifs"].items():
        f = f"facteur {m['facteur']}" if m["facteur"] is not None else m["statut"]
        print(f"  {k:70} {m['nb_confirmes']:>3} confirmes / {m['nb_retours']:>3} -> {f}")
    if not d["motifs"]:
        print("  aucun motif : comportement inchange")


if __name__ == "__main__":
    main()
