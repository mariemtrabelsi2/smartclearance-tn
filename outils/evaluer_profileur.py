"""Mesure de l'Agent 3 sur les schemas caches de l'historique synthetique.

Pour chaque importateur, on rejoue une operation a une date donnee en ne
laissant au profileur que l'historique anterieur, puis on compare a la verite.
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.profileur import analyser, HISTORIQUE_DEFAUT  # noqa: E402
from agents.stockage import lire_historique  # noqa: E402

VERITE = HISTORIQUE_DEFAUT.parent / "historique_verite.json"


def operation(l, decalage_jours=1):
    """Une ligne d'historique rejouee comme une DDM, a la date indiquee."""
    ddm = {"importateur": l["importateur"], "fournisseur": l["fournisseur"],
           "code_sh": l["code_sh"], "pays_origine": l["pays_origine"]}
    return ddm, (l["date"] + timedelta(days=decalage_jours)).isoformat()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    v = json.loads(VERITE.read_text(encoding="utf-8"))
    h = lire_historique()
    par_imp = {}
    for l in sorted(h, key=lambda l: l["date"]):
        par_imp.setdefault(l["importateur"], []).append(l)

    attendus = {}   # importateur -> (ddm, date, type attendu)
    for d in v["derive_prix"]:
        attendus[d["importateur"]] = (*operation(par_imp[d["importateur"]][-1]), "derive_prix")
    for d in v["changement_secteur"]:
        # Premiere operation dans le nouveau chapitre : c'est la qu'il faut alerter.
        l = next(l for l in par_imp[d["importateur"]] if l["code_sh"][:2] == d["chapitre_apres"])
        attendus[d["importateur"]] = (*operation(l, 0), "changement_secteur")
    fp = v["fournisseur_partage"]
    for imp in fp["importateurs"]:
        l = [l for l in par_imp[imp] if l["fournisseur"] == fp["fournisseur"]][-1]
        attendus[imp] = (*operation(l), "fournisseur_partage")

    trouves, print_lignes = 0, []
    for imp, (ddm, dt, type_att) in attendus.items():
        types = [a.type for a in analyser(ddm, None, dt).alertes]
        ok = type_att in types
        trouves += ok
        print_lignes.append(f"{'OK' if ok else '!!'} {imp:28} attendu={type_att:20} obtenu={types}")

    normaux = [i for i in par_imp if i not in attendus]
    fausses = []
    for imp in normaux:
        ddm, dt = operation(par_imp[imp][-1])
        types = [a.type for a in analyser(ddm, None, dt).alertes]
        if types:
            fausses.append((imp, types))

    print("\n".join(print_lignes))
    print(f"\nSchemas caches retrouves : {trouves}/{len(attendus)}")
    print(f"Importateurs normaux avec alerte : {len(fausses)}/{len(normaux)}")
    for imp, t in fausses:
        print(f"   {imp}: {t}")


if __name__ == "__main__":
    main()
