"""MESURE (non branchee) : reseau de fournisseurs, rapport section 4.4.

    py outils/evaluer_reseau_fournisseurs.py

Pour chaque fournisseur de donnees/historique.csv : importateurs DISTINCTS et
part de ses declarations "en alerte de prix". L'historique n'a pas de colonne
d'alerte : une declaration est comptee en alerte de prix si son prix au kilo est
<= 70 % de la mediane de son code SH dans l'historique (meme definition que le
controle fournisseur_partage deja en service).

Puis simulation sur les 3 graines : quels dossiers recevraient l'alerte, dont
combien de dossiers propres. Rien n'est modifie.
"""
import glob
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import stockage  # noqa: E402

SEUIL_PRIX = 0.7


def distribution(historique):
    medianes = {}
    for l in historique:
        medianes.setdefault(l["code_sh"], []).append(l["prix_kg"])
    medianes = {k: statistics.median(v) for k, v in medianes.items()}
    par_four = {}
    for l in historique:
        f = par_four.setdefault(l["fournisseur"], {"declarations": 0, "en_alerte": 0,
                                                  "importateurs": set(), "importateurs_en_alerte": set()})
        f["declarations"] += 1
        f["importateurs"].add(l["importateur"])
        if l["prix_kg"] <= SEUIL_PRIX * medianes[l["code_sh"]]:
            f["en_alerte"] += 1
            f["importateurs_en_alerte"].add(l["importateur"])
    return {k: {"declarations": v["declarations"], "importateurs": len(v["importateurs"]),
                "importateurs_en_alerte": len(v["importateurs_en_alerte"]),
                "part_alerte": round(v["en_alerte"] / v["declarations"], 3)}
            for k, v in par_four.items()}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    h = stockage.lire_historique()
    dist = distribution(h)
    print(f"1. DISTRIBUTION REELLE : {len(dist)} fournisseurs, {len(h)} declarations (historique synthetique)\n")
    print(f"   {'fournisseur':34} {'decl.':>5} {'import.':>7} {'import. en alerte':>17} {'part alerte':>11}")
    for f, v in sorted(dist.items(), key=lambda x: (-x[1]["part_alerte"], -x[1]["importateurs"])):
        print(f"   {f:34} {v['declarations']:>5} {v['importateurs']:>7} {v['importateurs_en_alerte']:>17} "
              f"{v['part_alerte']:>11.0%}")
    parts = sorted({v["part_alerte"] for v in dist.values()})
    print(f"\n   Valeurs distinctes de la part d'alerte : {[f'{p:.0%}' for p in parts]}")
    imports = sorted({v["importateurs"] for v in dist.values()})
    print(f"   Valeurs distinctes du nombre d'importateurs : {imports}")

    # Seuils lus dans la distribution : le plus grand ecart entre deux valeurs
    # successives de la part d'alerte separe "bruit" et "noeud".
    ecarts = [(parts[i + 1] - parts[i], parts[i], parts[i + 1]) for i in range(len(parts) - 1)]
    saut, bas, haut = max(ecarts)
    seuil_part = round((bas + haut) / 2, 2)
    noeuds = {f: v for f, v in dist.items() if v["part_alerte"] >= seuil_part}
    seuil_imp = min(v["importateurs"] for v in noeuds.values()) if noeuds else None
    print(f"\n2. SEUILS PROPOSES (plus grand saut de la distribution) : part d'alerte entre "
          f"{bas:.0%} et {haut:.0%} -> seuil {seuil_part:.0%} ; importateurs distincts >= {seuil_imp} "
          f"(minimum observe au-dessus du seuil)")
    print(f"   Fournisseurs au-dessus : {sorted(noeuds)}")

    print("\n3. SIMULATION SUR LES 3 GRAINES (aucun branchement) :")
    total, propres, liste = 0, 0, []
    for base in ["dossiers", "dossiers_graine99", "dossiers_graine123"]:
        verite = {d["dossier"]: d["propre"] for d in
                  json.load(open(f"{base}/verite_terrain.json", encoding="utf-8"))["dossiers"]}
        for d in sorted(glob.glob(base + "/dossier_*")):
            ddm = json.load(open(Path(d) / "ddm.json", encoding="utf-8"))
            v = dist.get(ddm.get("fournisseur"))
            nom = Path(d).name
            if v and v["part_alerte"] >= seuil_part and v["importateurs"] >= seuil_imp:
                total += 1; propres += verite[nom]
                liste.append((base, nom, ddm["fournisseur"], verite[nom]))
    print(f"   Alertes nouvelles : {total} | dont sur dossiers propres : {propres}")
    for b, n, f, p in liste:
        print(f"   {b}/{n} {'PROPRE' if p else ''} fournisseur {f}")
    fours = sorted({json.load(open(Path(d) / "ddm.json", encoding="utf-8"))["fournisseur"]
                    for d in glob.glob("dossiers*/dossier_*")})
    print("   Fournisseurs des 60 dossiers et leur profil dans l'historique :")
    for f in fours:
        v = dist.get(f, {})
        print(f"     {f:34} importateurs {v.get('importateurs', 0)}, part d'alerte {v.get('part_alerte', 0):.0%}")


if __name__ == "__main__":
    main()
