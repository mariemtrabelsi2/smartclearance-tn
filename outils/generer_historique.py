"""Historique SYNTHETIQUE de declarations pour l'Agent 3 (profileur).

    py outils/generer_historique.py   ->  donnees/historique.csv + donnees/historique_verite.json

30 importateurs, 500 declarations sur 24 mois (2024-01 a 2025-12), en majorite
coherentes, avec trois schemas caches documentes dans la verite terrain.
Les 5 importateurs et 5 fournisseurs du generateur de dossiers y figurent comme
distributeurs etablis et diversifies : sans eux, l'Agent 3 n'aurait aucun
historique a consulter pendant la demonstration.
"""
import csv
import json
import random
from pathlib import Path

random.seed(2026)
RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "donnees"

# code_sh -> prix de reference USD/kg
PRODUITS = {
    "852872": 23.9, "851713": 142.0, "870322": 9.5, "151090": 4.2, "940360": 3.8,
    "610910": 18.5, "392690": 3.5, "721049": 1.1, "300490": 60.0, "090111": 3.2,
    "847130": 180.0, "640399": 25.0,
}
PRODUITS_GENERATEUR = ["852872", "851713", "870322", "151090", "940360", "610910"]

FOURNISSEURS_GENERATEUR = [
    ("SHENZHEN BRIGHT TRADING CO. LTD", "CN"), ("ANADOLU IHRACAT A.S.", "TR"),
    ("LOMBARDIA FORNITURE SRL", "IT"), ("NILE DELTA EXPORT", "EG"),
    ("IBERIA SUMINISTROS SL", "ES"),
]
IMPORTATEURS_GENERATEUR = [
    "STE ESSALEM IMPORT SARL", "COMPTOIR DU SUD SA", "MEDITEX TRADING SARL",
    "SOCIETE NOUR DISTRIBUTION", "EL BAHIA NEGOCE SARL",
]
PAYS = ["CN", "TR", "IT", "EG", "ES", "DE", "FR", "IN"]
FOURNISSEURS_POOL = [(f"{p} SUPPLIER {i:02d}", p) for p in PAYS for i in range(1, 4)]
FOURNISSEUR_PARTAGE = ("GLOBAL SOURCING FZE", "AE")

NOMS = ["ATLAS", "CARTHAGE", "SAHEL", "JASMIN", "OASIS", "MEDINA", "ZITOUNA", "KAIROUAN",
        "BIZERTE", "SFAX", "DJERBA", "TABARKA", "HAMMAMET", "MONASTIR", "NABEUL", "GABES",
        "TOZEUR", "KELIBIA", "SOUSSE", "MAHDIA", "BEJA", "ZAGHOUAN", "GAFSA", "SILIANA", "KEF"]


def date_du_mois(m):
    return f"{2024 + m // 12}-{m % 12 + 1:02d}-{random.randint(1, 28):02d}"


def ligne(imp, four, pays, sh, mois, facteur_prix=1.0):
    poids = round(random.uniform(200, 20000), 1)
    prix = PRODUITS[sh] * facteur_prix * random.uniform(0.9, 1.1)
    return {"importateur": imp, "fournisseur": four, "code_sh": sh, "pays_origine": pays,
            "date": date_du_mois(mois), "valeur": round(prix * poids, 2), "poids": poids,
            "prix_kg": round(prix, 4)}


def main():
    SORTIE.mkdir(exist_ok=True)
    lignes, verite = [], {"derive_prix": [], "changement_secteur": [], "fournisseur_partage": {}}
    autres = [f"{n} IMPORT SARL" for n in NOMS]      # 25 importateurs synthetiques
    derive, secteur, partage, normaux = autres[:3], autres[3:5], autres[5:9], autres[9:]

    # Distributeurs du generateur : tous produits, tous fournisseurs du generateur.
    for imp in IMPORTATEURS_GENERATEUR:
        for _ in range(20):
            four, pays = random.choice(FOURNISSEURS_GENERATEUR)
            lignes.append(ligne(imp, four, pays, random.choice(PRODUITS_GENERATEUR),
                                random.randint(0, 23)))

    # Schema 1 : derive de prix de -5 % par trimestre, un seul produit, fournisseur dedie.
    for i, imp in enumerate(derive):
        sh = ["847130", "300490", "640399"][i]
        four = (f"DERIVE SUPPLIER {i + 1}", "CN")
        for k in range(14):
            mois = round(k * 23 / 13)
            lignes.append(ligne(imp, *four, sh, mois, facteur_prix=0.95 ** (mois / 3)))
        verite["derive_prix"].append({"importateur": imp, "code_sh": sh,
                                      "pente_pct_par_trimestre": -5.0})

    # Schema 2 : changement brutal de secteur au mois 18.
    for i, imp in enumerate(secteur):
        avant, apres = [("090111", "851713"), ("721049", "300490")][i]
        four_avant, four_apres = random.choice(FOURNISSEURS_POOL), random.choice(FOURNISSEURS_POOL)
        for k in range(18):
            mois = random.randint(0, 17) if k < 12 else random.randint(18, 23)
            f, sh = (four_avant, avant) if mois < 18 else (four_apres, apres)
            lignes.append(ligne(imp, *f, sh, mois))
        verite["changement_secteur"].append({"importateur": imp, "mois": 18,
                                             "chapitre_avant": avant[:2], "chapitre_apres": apres[:2]})

    # Schema 3 : un fournisseur partage par 4 importateurs, tous a -40 %.
    for imp in partage:
        sh = random.choice(["392690", "610910", "640399"])
        for k in range(12):
            mois = random.randint(0, 23)
            if k % 2 == 0:
                lignes.append(ligne(imp, *FOURNISSEUR_PARTAGE, sh, mois, facteur_prix=0.6))
            else:
                lignes.append(ligne(imp, *random.choice(FOURNISSEURS_POOL), sh, mois))
    verite["fournisseur_partage"] = {"fournisseur": FOURNISSEUR_PARTAGE[0],
                                     "importateurs": partage, "facteur_prix": 0.6}

    # Importateurs coherents : 1 ou 2 produits, 2 ou 3 fournisseurs habituels.
    reste = 500 - len(lignes)
    for j, imp in enumerate(normaux):
        n = reste // len(normaux) + (1 if j < reste % len(normaux) else 0)
        shs = random.sample(sorted(PRODUITS), random.choice([1, 2]))
        fours = random.sample(FOURNISSEURS_POOL, random.choice([2, 3]))
        for _ in range(n):
            lignes.append(ligne(imp, *random.choice(fours), random.choice(shs),
                                random.randint(0, 23)))

    lignes.sort(key=lambda l: l["date"])
    with open(SORTIE / "historique.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0]))
        w.writeheader()
        w.writerows(lignes)
    verite.update({"nb_declarations": len(lignes),
                   "nb_importateurs": len({l["importateur"] for l in lignes}),
                   "periode": f"{lignes[0]['date'][:7]} a {lignes[-1]['date'][:7]}"})
    (SORTIE / "historique_verite.json").write_text(json.dumps(verite, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
    print(f"{len(lignes)} declarations, {verite['nb_importateurs']} importateurs, {verite['periode']}")


if __name__ == "__main__":
    main()
