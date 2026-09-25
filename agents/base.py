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