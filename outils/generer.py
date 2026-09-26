#!/usr/bin/env python3
"""
Generateur de dossiers d'importation FICTIFS pour tester le moteur d'anomalies.

    python3 generer.py            # 20 dossiers dans ./sortie/
    python3 generer.py 40         # 40 dossiers
    python3 generer.py 20 99 out  # 20 dossiers, graine 99, dans ./out/

Produit, par dossier :
    dossier_NN/facture.pdf        (scan-like, a lire par OCR/LLM)
    dossier_NN/colisage.pdf
    dossier_NN/transport.pdf
    dossier_NN/ddm.json           (la declaration, deja structuree)
    dossier_NN/certificat_origine.pdf
Plus, a la racine :
    verite_terrain.json           <- ce que le moteur DOIT trouver

Toutes les entreprises, adresses et numeros sont inventes.
"""
import os, sys, json, random
from datetime import date, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

random.seed(7)  # reproductible : memes dossiers a chaque execution

PRODUITS = [
    # (code SH, designation facture, designation "officielle", prix normal $/kg, kg par unite)
    ("852872", "LED TV 43 inch Smart", "Moniteurs et projecteurs", 23.9, 8.0),
    ("851713", "Smartphone 6.5 inch 128GB", "Telephones intelligents", 142.0, 0.2),
    ("870322", "Passenger car 1200cc", "Voitures de tourisme", 9.5, 1100.0),
    ("151090", "Olive oil virgin 5L", "Huiles d'olive", 4.2, 5.0),
    ("940360", "Wooden office desk", "Meubles en bois", 3.8, 35.0),
    ("610910", "Cotton T-shirt", "T-shirts en coton", 18.5, 0.2),
]
FOURNISSEURS = [
    ("SHENZHEN BRIGHT TRADING CO. LTD", "Shenzhen, China", "CN"),
    ("ANADOLU IHRACAT A.S.", "Izmir, Turkiye", "TR"),
    ("LOMBARDIA FORNITURE SRL", "Milano, Italia", "IT"),
    ("NILE DELTA EXPORT", "Alexandria, Egypt", "EG"),
    ("IBERIA SUMINISTROS SL", "Valencia, Espana", "ES"),
]
IMPORTATEURS = [
    "STE ESSALEM IMPORT SARL", "COMPTOIR DU SUD SA", "MEDITEX TRADING SARL",
    "SOCIETE NOUR DISTRIBUTION", "EL BAHIA NEGOCE SARL",
]
PORTS = {"CN": "Shanghai", "TR": "Mersin", "IT": "Genova", "EG": "Alexandria", "ES": "Valencia"}

# Les 8 anomalies que le moteur doit savoir trouver
ANOMALIES = [
    "ecart_quantite",       # facture != colisage
    "ecart_poids",          # colisage != DDM
    "ecart_valeur",         # facture != DDM
    "ecart_origine",        # transport != DDM
    "erreur_arithmetique",  # qte x PU != total sur la facture
    "sous_evaluation",      # prix/kg tres sous la reference
    "poids_invraisemblable",# poids unitaire physiquement impossible
    "designation_vs_sh",    # libelle facture incompatible avec le code declare
]


# ------------------------------------------------------------------ rendu PDF
def entete(c, titre, ref):
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20*mm, 277*mm, titre)
    c.setFont("Helvetica", 8)
    c.drawString(20*mm, 271*mm, f"Ref: {ref}")
    c.line(20*mm, 268*mm, 190*mm, 268*mm)


def ligne(c, y, gauche, droite, gras=False):
    c.setFont("Helvetica-Bold" if gras else "Helvetica", 9)
    c.drawString(22*mm, y*mm, str(gauche))
    c.drawRightString(188*mm, y*mm, str(droite))
    return y - 6


def facture_pdf(path, d):
    c = canvas.Canvas(path, pagesize=A4)
    entete(c, "COMMERCIAL INVOICE", d["ref_facture"])
    y = 258
    c.setFont("Helvetica-Bold", 10); c.drawString(22*mm, y*mm, "SELLER")
    c.setFont("Helvetica", 9)
    c.drawString(22*mm, (y-6)*mm, d["fournisseur"])
    c.drawString(22*mm, (y-11)*mm, d["fournisseur_ville"])
    c.setFont("Helvetica-Bold", 10); c.drawString(110*mm, y*mm, "BUYER")
    c.setFont("Helvetica", 9)
    c.drawString(110*mm, (y-6)*mm, d["importateur"])
    c.drawString(110*mm, (y-11)*mm, "Tunis, Tunisia")
    y -= 24
    y = ligne(c, y, "Date", d["date"])
    y = ligne(c, y, "Incoterm", "CIF Rades")
    y = ligne(c, y, "Currency", "USD")
    y -= 4
    c.line(20*mm, y*mm, 190*mm, y*mm); y -= 7
    c.setFont("Helvetica-Bold", 9)
    c.drawString(22*mm, y*mm, "DESCRIPTION")
    c.drawString(115*mm, y*mm, "QTY")
    c.drawString(140*mm, y*mm, "UNIT PRICE")
    c.drawRightString(188*mm, y*mm, "AMOUNT")
    y -= 6; c.line(20*mm, y*mm, 190*mm, y*mm); y -= 7
    c.setFont("Helvetica", 9)
    c.drawString(22*mm, y*mm, d["designation_facture"][:48])
    c.drawString(115*mm, y*mm, f"{d['qte_facture']}")
    c.drawString(140*mm, y*mm, f"{d['pu']:.2f}")
    c.drawRightString(188*mm, y*mm, f"{d['total_facture']:,.2f}")
    y -= 12
    c.line(120*mm, y*mm, 190*mm, y*mm); y -= 7
    c.setFont("Helvetica-Bold", 10)
    c.drawString(122*mm, y*mm, "TOTAL CIF USD")
    c.drawRightString(188*mm, y*mm, f"{d['total_facture']:,.2f}")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm, "Document fictif genere pour test - aucune valeur commerciale")
    c.save()


def colisage_pdf(path, d):
    c = canvas.Canvas(path, pagesize=A4)
    entete(c, "PACKING LIST", d["ref_facture"])
    y = 255
    y = ligne(c, y, "Shipper", d["fournisseur"])
    y = ligne(c, y, "Consignee", d["importateur"])
    y = ligne(c, y, "Container", d["conteneur"])
    y -= 6
    c.line(20*mm, y*mm, 190*mm, y*mm); y -= 8
    y = ligne(c, y, "Goods", d["designation_facture"][:44], gras=True)
    y = ligne(c, y, "Number of packages", f"{d['colis']} cartons")
    y = ligne(c, y, "Quantity", f"{d['qte_colisage']} pcs")
    y = ligne(c, y, "Net weight", f"{d['poids_colisage']:,.1f} kg")
    y = ligne(c, y, "Gross weight", f"{d['poids_colisage']*1.06:,.1f} kg")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm, "Document fictif genere pour test - aucune valeur commerciale")
    c.save()


# Justificatifs joints a certaines sous-evaluations. Cycle deterministe (pas de
# tirage) pour ne pas decaler la suite aleatoire : les autres pieces restent
# identiques a celles generees avant l'ajout des justificatifs.
PAYS_NOM = {"CN": "China", "TR": "Turkiye", "IT": "Italy", "EG": "Egypt", "ES": "Spain"}


def certificat_initial(d, rng):
    """Certificat coherent par defaut avec la facture, le colisage et la DDM.
    Tire avec un generateur SEPARE : la suite aleatoire principale, donc les
    autres pieces, reste identique a celle d'avant l'ajout du certificat."""
    origine = d["origine_ddm"]
    ville = (d["fournisseur_ville"].split(",")[0] if origine == d["origine_transport"]
             else PORTS[origine])
    emission = date.fromisoformat(d["date"]) + timedelta(days=rng.randint(1, 5))
    return {"ref": f"CO-2026-{rng.randint(100000, 999999)}",
            "autorite": f"Chamber of Commerce of {ville}, {PAYS_NOM[origine]}",
            "exportateur": d["fournisseur"], "destinataire": d["importateur"],
            "origine": origine, "designation": d["designation_facture"],
            "quantite": d["qte_facture"], "poids": d["poids_colisage"],
            "date": emission.isoformat()}


# Anomalies portees par le certificat. Liste separee d'ANOMALIES : les ajouter
# au tirage principal decalerait toute la suite aleatoire et changerait tous
# les dossiers, rendant impossible la comparaison avec les jeux precedents.
ANOMALIES_CERTIFICAT = [
    "ecart_origine_certificat",        # certificat != DDM sur l'origine
    "autorite_emettrice_incoherente",  # chambre de commerce hors du pays certifie
    "ecart_exportateur",               # exportateur du certificat != vendeur facture
]


def injecter_certificat(co, d, quelles, rng):
    posees = []
    for a in quelles:
        if a == "ecart_origine_certificat":
            autre = rng.choice([p for p in PAYS_NOM if p not in (d["origine_ddm"], d["origine_transport"])])
            co["origine"] = autre
            co["autorite"] = f"Chamber of Commerce of {PORTS[autre]}, {PAYS_NOM[autre]}"
            posees.append({"type": a, "detail": f"certificat {autre} vs DDM {d['origine_ddm']}"})
        elif a == "autorite_emettrice_incoherente":
            autre = rng.choice([p for p in PAYS_NOM if p != co["origine"]])
            co["autorite"] = f"Chamber of Commerce of {PORTS[autre]}, {PAYS_NOM[autre]}"
            posees.append({"type": a, "detail":
                f"origine certifiee {co['origine']} mais chambre de {PORTS[autre]} ({autre})"})
        elif a == "ecart_exportateur":
            autre = rng.choice([f[0] for f in FOURNISSEURS if f[0] != d["fournisseur"]])
            co["exportateur"] = autre
            posees.append({"type": a, "detail":
                f"facture {d['fournisseur']} vs certificat {autre}"})
    return posees


def certificat_pdf(path, co):
    c = canvas.Canvas(path, pagesize=A4)
    entete(c, "CERTIFICATE OF ORIGIN", co["ref"])
    y = 255
    y = ligne(c, y, "Issuing authority", co["autorite"])
    y = ligne(c, y, "Exporter", co["exportateur"])
    y = ligne(c, y, "Consignee", co["destinataire"])
    y = ligne(c, y, "Country of origin", co["origine"], gras=True)
    y = ligne(c, y, "Goods", co["designation"][:44])
    y = ligne(c, y, "Quantity", f"{co['quantite']} pcs")
    y = ligne(c, y, "Net weight", f"{co['poids']:,.1f} kg")
    y = ligne(c, y, "Date of issue", co["date"])
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm, "Document fictif genere pour test - aucune valeur commerciale")
    c.save()


JUSTIFICATIFS = [
    {"titre": "COMMERCIAL AGREEMENT", "objet": "Volume discount 60% - valid until 2026-12-31",
     "detail": ("Discount rate", "60%"), "remise": 60},
    {"titre": "CREDIT NOTE", "objet": "End of series clearance",
     "detail": ("Credit granted", "20% of invoice value"), "remise": 20},
    {"titre": "PROMOTIONAL OFFER", "objet": "Black Friday campaign",
     "detail": ("Promotional discount", "30%"), "remise": 30},
]


def justificatif_pdf(path, d, j):
    c = canvas.Canvas(path, pagesize=A4)
    entete(c, j["titre"], d["ref_facture"])
    y = 255
    y = ligne(c, y, "Seller", d["fournisseur"])
    y = ligne(c, y, "Buyer", d["importateur"])
    y = ligne(c, y, "Subject", j["objet"], gras=True)
    y = ligne(c, y, *j["detail"])
    y = ligne(c, y, "Applies to invoice", d["ref_facture"])
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm, "Document fictif genere pour test - aucune valeur commerciale")
    c.save()


def transport_pdf(path, d):
    c = canvas.Canvas(path, pagesize=A4)
    entete(c, "BILL OF LADING", d["ref_transport"])
    y = 255
    y = ligne(c, y, "Vessel", d["navire"])
    y = ligne(c, y, "Port of loading", d["port_chargement"])
    y = ligne(c, y, "Port of discharge", "Rades, Tunisia")
    y = ligne(c, y, "Country of origin", d["origine_transport"], gras=True)
    y = ligne(c, y, "Container", d["conteneur"])
    y = ligne(c, y, "Packages", f"{d['colis']} cartons")
    y = ligne(c, y, "Gross weight", f"{d['poids_colisage']*1.06:,.1f} kg")
    y = ligne(c, y, "Shipper", d["fournisseur"])
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20*mm, 15*mm, "Document fictif genere pour test - aucune valeur commerciale")
    c.save()


# ------------------------------------------------------------- fabrication
def conteneur_iso6346(tire):
    """Remplace le 11e caractere par le vrai chiffre de controle ISO 6346.
    Calcul deterministe, aucun tirage : la suite aleatoire ne bouge pas.
    Avant cette correction, ~10 numeros sur 11 etaient non conformes."""
    valeurs, v = {}, 10
    for lettre in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if v % 11 == 0:
            v += 1
        valeurs[lettre] = v
        v += 1
    total = sum((valeurs[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(tire[:10]))
    return tire[:10] + str(total % 11 % 10)


def construire(i):
    sh, des_fact, des_off, prix_ref, kg_u = random.choice(PRODUITS)
    fo, ville, iso = random.choice(FOURNISSEURS)
    imp = random.choice(IMPORTATEURS)
    qte = random.choice([50, 100, 200, 500, 800, 1500])

    d = {
        "ref_facture": f"INV-2026-{1000+i}",
        "ref_transport": f"BL{random.randint(100000,999999)}",
        "conteneur": conteneur_iso6346(f"{random.choice(['MSCU','TGHU','CMAU'])}{random.randint(1000000,9999999)}"),
        "navire": random.choice(["MSC ALTAIR", "CMA CGM TARIK", "MAERSK SIROCCO"]),
        # Septembre ramene en aout, sans tirage supplementaire : avec le
        # certificat emis jusqu'a 5 jours apres, les pieces etaient datees
        # apres la demonstration (fin septembre 2026), donc "dans le futur".
        "date": f"2026-0{min(random.randint(1,9), 8)}-{random.randint(10,28)}",
        "fournisseur": fo, "fournisseur_ville": ville, "importateur": imp,
        "port_chargement": PORTS[iso],
        "origine_transport": iso,
        "designation_facture": des_fact,
        "sh_declare": sh,
        "qte_facture": qte,
        "colis": max(1, qte // random.choice([4, 6, 10])),
        "prix_ref_kg": prix_ref,
    }
    poids = round(qte * kg_u, 1)
    d["pu"] = round(prix_ref * kg_u, 2)
    d["total_facture"] = round(qte * d["pu"], 2)
    d["qte_colisage"] = qte
    d["poids_colisage"] = poids
    d["poids_ddm"] = poids
    d["valeur_ddm"] = d["total_facture"]
    d["origine_ddm"] = iso
    d["designation_ddm"] = des_off
    return d


def injecter(d, quelles):
    """Applique les anomalies demandees. Retourne la liste posee."""
    posees = []
    for a in quelles:
        if a == "ecart_quantite":
            d["qte_colisage"] = int(d["qte_facture"] * random.choice([1.4, 1.6, 0.7]))
            posees.append({"type": a, "detail":
                f"facture {d['qte_facture']} pcs vs colisage {d['qte_colisage']} pcs"})
        elif a == "ecart_poids":
            d["poids_ddm"] = round(d["poids_colisage"] * random.choice([0.62, 0.71]), 1)
            posees.append({"type": a, "detail":
                f"colisage {d['poids_colisage']} kg vs DDM {d['poids_ddm']} kg"})
        elif a == "ecart_valeur":
            d["valeur_ddm"] = round(d["total_facture"] * random.choice([0.55, 0.68]), 2)
            posees.append({"type": a, "detail":
                f"facture {d['total_facture']} USD vs DDM {d['valeur_ddm']} USD"})
        elif a == "ecart_origine":
            autre = random.choice([x for x in ["CN","TR","IT","EG","ES"]
                                   if x != d["origine_transport"]])
            d["origine_ddm"] = autre
            posees.append({"type": a, "detail":
                f"transport {d['origine_transport']} vs DDM {d['origine_ddm']}"})
        elif a == "erreur_arithmetique":
            faux = round(d["qte_facture"] * d["pu"] * 0.8, 2)
            d["total_facture"] = faux
            d["valeur_ddm"] = faux
            posees.append({"type": a, "detail":
                f"{d['qte_facture']} x {d['pu']} != {faux} sur la facture"})
        elif a == "sous_evaluation":
            f = random.choice([0.18, 0.25, 0.32])
            d["pu"] = round(d["pu"] * f, 2)
            d["total_facture"] = round(d["qte_facture"] * d["pu"], 2)
            d["valeur_ddm"] = d["total_facture"]
            prix_kg = d["valeur_ddm"] / d["poids_ddm"]
            posees.append({"type": a, "detail":
                f"{prix_kg:.2f} USD/kg vs reference {d['prix_ref_kg']} USD/kg"})
        elif a == "poids_invraisemblable":
            d["poids_ddm"] = round(d["poids_colisage"] * 0.04, 1)
            d["poids_colisage"] = d["poids_ddm"]
            posees.append({"type": a, "detail":
                f"{d['poids_ddm']/d['qte_facture']:.3f} kg par unite pour "
                f"'{d['designation_facture']}'"})
        elif a == "designation_vs_sh":
            d["sh_declare"] = "732690"   # "ouvrages en fer" : droits plus faibles
            d["designation_ddm"] = "Autres ouvrages en fer ou acier"
            posees.append({"type": a, "detail":
                f"facture dit '{d['designation_facture']}' mais SH declare 732690"})
    return posees


def ddm_json(d):
    """La declaration en detail, deja structuree (elle vient de SINDA)."""
    return {
        "numero_ddm": f"DDM-2026-{random.randint(100000,999999)}",
        "bureau": "Rades",
        "regime": "Mise a la consommation",
        "importateur": d["importateur"],
        "fournisseur": d["fournisseur"],
        "reference_facture": d["ref_facture"],
        "code_sh": d["sh_declare"],
        "designation": d["designation_ddm"],
        "pays_origine": d["origine_ddm"],
        "quantite": d["qte_facture"],
        "poids_net_kg": d["poids_ddm"],
        "valeur_cif_usd": d["valeur_ddm"],
        "incoterm": "CIF",
        "conteneur": d["conteneur"],
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    graine = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    random.seed(graine)
    rng_co = random.Random(graine * 1000 + 17)   # tout ce qui touche au certificat
    base = sys.argv[3] if len(sys.argv) > 3 else "sortie"
    os.makedirs(base, exist_ok=True)

    # 30% de dossiers PROPRES : indispensables pour mesurer les fausses alertes
    n_propres = max(3, round(n * 0.30))
    plan = [[] for _ in range(n_propres)]
    reste = n - n_propres

    # Chaque type doit apparaitre au moins une fois, sinon un detecteur
    # n'est jamais teste et la mesure est trompeuse.
    pool = list(ANOMALIES)
    while len(pool) < reste:
        pool.append(random.choice(ANOMALIES))
    random.shuffle(pool)
    for k in range(reste):
        if k % 3 == 0 and k + 1 < len(pool):     # un tiers a 2 anomalies
            a, b = pool[k], random.choice([x for x in ANOMALIES if x != pool[k]])
            plan.append([a, b])
        else:
            plan.append([pool[k]])
    random.shuffle(plan)

    # Chaque anomalie du certificat au moins une fois, sur un dossier DEJA
    # anormal : les dossiers propres restent propres, la mesure des fausses
    # alertes reste comparable d'un jeu a l'autre.
    anormaux = [i for i, q in enumerate(plan, start=1) if q]
    cibles = {}
    for t, i in zip(ANOMALIES_CERTIFICAT, rng_co.sample(anormaux, len(ANOMALIES_CERTIFICAT))):
        cibles.setdefault(i, []).append(t)

    verite, total_anos, n_justif = [], 0, 0
    for i, quelles in enumerate(plan, start=1):
        d = construire(i)
        posees = injecter(d, quelles)
        co = certificat_initial(d, rng_co)
        posees += injecter_certificat(co, d, cibles.get(i, []), rng_co)
        total_anos += len(posees)

        rep = os.path.join(base, f"dossier_{i:02d}")
        os.makedirs(rep, exist_ok=True)
        facture_pdf(os.path.join(rep, "facture.pdf"), d)
        certificat_pdf(os.path.join(rep, "certificat_origine.pdf"), co)
        colisage_pdf(os.path.join(rep, "colisage.pdf"), d)
        transport_pdf(os.path.join(rep, "transport.pdf"), d)
        with open(os.path.join(rep, "ddm.json"), "w", encoding="utf-8") as f:
            json.dump(ddm_json(d), f, indent=2, ensure_ascii=False)

        entree = {
            "dossier": f"dossier_{i:02d}",
            "propre": len(posees) == 0,
            "nb_anomalies": len(posees),
            "anomalies": posees,
            "justification_presente": False,
        }
        if any(a["type"] == "sous_evaluation" for a in posees) and n_justif < len(JUSTIFICATIFS):
            j = JUSTIFICATIFS[n_justif]
            justificatif_pdf(os.path.join(rep, "justificatif.pdf"), d, j)
            entree["justification_presente"] = True
            entree["justificatif"] = {"type": j["titre"], "remise_annoncee_pct": j["remise"]}
            n_justif += 1
        verite.append(entree)

    with open(os.path.join(base, "verite_terrain.json"), "w", encoding="utf-8") as f:
        json.dump({"nb_dossiers": n, "nb_anomalies_posees": total_anos,
                   "dossiers": verite}, f, indent=2, ensure_ascii=False)

    propres = sum(1 for v in verite if v["propre"])
    print(f"{n} dossiers generes dans ./{base}/")
    print(f"  propres (aucune anomalie) : {propres}")
    print(f"  avec anomalies            : {n - propres}")
    print(f"  total anomalies posees    : {total_anos}")
    print()
    compte = {}
    for v in verite:
        for a in v["anomalies"]:
            compte[a["type"]] = compte.get(a["type"], 0) + 1
    print("Repartition par type :")
    for t in ANOMALIES + ANOMALIES_CERTIFICAT:
        print(f"  {t:<24} {compte.get(t, 0)}")
    print(f"\nVerite terrain : {base}/verite_terrain.json")


if __name__ == "__main__":
    main()
