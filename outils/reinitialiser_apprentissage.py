"""Retire tous les ajustements appris. Le feedback n'est PAS touche.

    py outils/reinitialiser_apprentissage.py

Le fichier courant est archive (donnees/ajustements_archive/) avant d'etre
retire : la remise a zero est tracee, et reversible (on peut aussi tout
recalculer depuis le feedback avec outils/recalculer_ajustements.py).
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import apprentissage  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    courant = apprentissage.AJUSTEMENTS_DEFAUT
    if not courant.exists():
        print("Aucun ajustement actif : rien a reinitialiser.")
        return
    archive = courant.parent / "ajustements_archive"
    archive.mkdir(exist_ok=True)
    cible = archive / f"ajustements_{datetime.now():%Y%m%d_%H%M%S}.json"
    shutil.move(courant, cible)
    print(f"Ajustements retires (archive : {cible}). Feedback intact.")


if __name__ == "__main__":
    main()
