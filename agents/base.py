"""Le formulaire que tous les agents remplissent."""
from dataclasses import dataclass, field, asdict
from typing import Any

NIVEAU_CONTRADICTION = 1   # aucune explication legitime possible
NIVEAU_ECART = 2           # une explication legitime existe (solde, promo)


@dataclass
class Alerte:
    type: str
    niveau: int
    message: str
    preuve: dict
    source: str
    gravite: int

    def to_dict(self):
        return asdict(self)


@dataclass
class RapportAgent:
    agent: str
    statut: str = "OK"
    alertes: list = field(default_factory=list)
    donnees: dict = field(default_factory=dict)
    non_lus: list = field(default_factory=list)

    def ajouter(self, **kw):
        self.alertes.append(Alerte(**kw))
        self.statut = "ALERTE"

    def to_dict(self):
        return {
            "agent": self.agent,
            "statut": self.statut,
            "alertes": [a.to_dict() for a in self.alertes],
            "donnees": self.donnees,
            "non_lus": self.non_lus,
        }

# ---------------- Routage : ce que chaque agent coute et quand il tourne ----------------
# Declaration seulement : la decision d'executer appartient au coordinateur
# (orchestrateur.POLITIQUE). Aucune logique metier ici.

COUT_FAIBLE = "faible"
COUT_ELEVE = "eleve"
DEPLOYE = "deploye"
NON_DEPLOYE = "non deploye"

MOTIF_SYSTEMATIQUE = "contrôle systématique, coût négligeable"
MOTIF_NON_DEPLOYE = "agent non déployé sur cette installation"


def toujours(contexte):
    return True, MOTIF_SYSTEMATIQUE


def jamais_non_deploye(contexte):
    return False, MOTIF_NON_DEPLOYE


@dataclass(frozen=True)
class FicheAgent:
    nom: str                                   # libelle affiche a l'inspecteur
    cout: str                                  # COUT_FAIBLE ou COUT_ELEVE
    condition_execution: Any = toujours        # contexte -> (bool, motif)
    etat: str = DEPLOYE


# Ordre = ordre d'execution et d'affichage.
AGENTS = {
    "documentaire": FicheAgent("Inspecteur documentaire", COUT_FAIBLE),
    "prix": FicheAgent("Analyste prix", COUT_FAIBLE),
    "profil": FicheAgent("Profileur", COUT_FAIBLE),
    "registre": FicheAgent("Registre des références", COUT_FAIBLE),
    # Emplacement reserve : declare pour montrer ou il s'insererait, mais rien
    # n'est installe. Il ne calcule rien et ne produit aucune alerte.
    "imagerie": FicheAgent("Analyse d'imagerie radiographique", COUT_ELEVE,
                           condition_execution=jamais_non_deploye, etat=NON_DEPLOYE),
}
