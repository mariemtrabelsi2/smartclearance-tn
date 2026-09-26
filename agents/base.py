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


# ---- Preconditions : "cet agent a-t-il de quoi travailler ?" ----
# Distinctes du cout. Elles portent sur la PRESENCE des donnees, jamais sur
# leur valeur : un dossier qui "a l'air propre" ne fait sauter aucun agent.
# Chaque precondition teste exactement ce que l'agent utilise.

def _present(v):
    return v is not None and str(v).strip() != ""


def sans_precondition(contexte):
    return True, ""


def precondition_prix(contexte):
    ddm = contexte["ddm"]
    # Valeur en USD, ou dans une autre devise (l'agent la convertit lui-meme).
    valeur = _present(ddm.get("valeur_cif_usd")) or _present(ddm.get("valeur_cif"))
    if valeur and _present(ddm.get("poids_net_kg")):
        return True, ""
    return False, "valeur ou poids manquant"


def precondition_profil(contexte):
    if _present(contexte["ddm"].get("importateur")):
        return True, ""
    return False, "importateur non identifié"


def precondition_registre(contexte):
    # L'agent prend la reference lue sur la facture, et a defaut celle de la
    # DDM : il n'a de quoi travailler que si l'une des deux existe.
    ddm, facture = contexte["ddm"], contexte.get("facture") or {}
    if not (_present(facture.get("reference")) or _present(ddm.get("reference_facture"))):
        return False, "référence de facture non lue"
    if not _present(ddm.get("numero_ddm")):
        return False, "numéro de DDM absent"
    return True, ""


@dataclass(frozen=True)
class FicheAgent:
    nom: str                                   # libelle affiche a l'inspecteur
    cout: str                                  # COUT_FAIBLE ou COUT_ELEVE
    condition_execution: Any = toujours        # contexte -> (bool, motif)
    etat: str = DEPLOYE
    precondition: Any = sans_precondition      # contexte -> (bool, motif)


# Ordre = ordre d'execution et d'affichage.
AGENTS = {
    # Aucune precondition : c'est lui qui constate qu'un dossier est illisible.
    "documentaire": FicheAgent("Inspecteur documentaire", COUT_FAIBLE),
    "prix": FicheAgent("Analyste prix", COUT_FAIBLE, precondition=precondition_prix),
    "profil": FicheAgent("Profileur", COUT_FAIBLE, precondition=precondition_profil),
    "registre": FicheAgent("Registre des références", COUT_FAIBLE, precondition=precondition_registre),
    # Emplacement reserve : declare pour montrer ou il s'insererait, mais rien
    # n'est installe. Il ne calcule rien et ne produit aucune alerte.
    "imagerie": FicheAgent("Analyse d'imagerie radiographique", COUT_ELEVE,
                           condition_execution=jamais_non_deploye, etat=NON_DEPLOYE),
}
