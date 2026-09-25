import json
from agents.base import RapportAgent, NIVEAU_CONTRADICTION

r = RapportAgent(agent="Inspecteur Documentaire")
r.ajouter(
    type="ecart_quantite",
    niveau=NIVEAU_CONTRADICTION,
    message="La facture annonce 200 pieces, le colisage 320.",
    preuve={"facture": 200, "colisage": 320, "ecart": 120},
    source="facture ligne 1 / colisage ligne 3",
    gravite=80,
)
r.non_lus.append("certificat_origine.date")

print(json.dumps(r.to_dict(), indent=2, ensure_ascii=False))