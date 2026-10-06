"""Données de référence : régions, départements, métiers, codes NAF, tranches d'effectif."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, tirets/apostrophes remplacés par des espaces."""
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower().replace("'", " ").replace("’", " ").replace("-", " ").replace("_", " ")
    return " ".join(texte.split())


# --------------------------------------------------------------------------- #
# Régions (codes INSEE) et départements
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Region:
    cle: str
    nom: str
    code: str
    departements: tuple[str, ...]


REGIONS: dict[str, Region] = {
    r.cle: r
    for r in [
        Region("ile-de-france", "Île-de-France", "11", ("75", "77", "78", "91", "92", "93", "94", "95")),
        Region("centre-val-de-loire", "Centre-Val de Loire", "24", ("18", "28", "36", "37", "41", "45")),
        Region("bourgogne-franche-comte", "Bourgogne-Franche-Comté", "27",
               ("21", "25", "39", "58", "70", "71", "89", "90")),
        Region("normandie", "Normandie", "28", ("14", "27", "50", "61", "76")),
        Region("hauts-de-france", "Hauts-de-France", "32", ("02", "59", "60", "62", "80")),
        Region("grand-est", "Grand Est", "44", ("08", "10", "51", "52", "54", "55", "57", "67", "68", "88")),
        Region("pays-de-la-loire", "Pays de la Loire", "52", ("44", "49", "53", "72", "85")),
        Region("bretagne", "Bretagne", "53", ("22", "29", "35", "56")),
        Region("nouvelle-aquitaine", "Nouvelle-Aquitaine", "75",
               ("16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87")),
        Region("occitanie", "Occitanie", "76",
               ("09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82")),
        Region("auvergne-rhone-alpes", "Auvergne-Rhône-Alpes", "84",
               ("01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74")),
        Region("provence-alpes-cote-d-azur", "Provence-Alpes-Côte d'Azur", "93",
               ("04", "05", "06", "13", "83", "84")),
        Region("corse", "Corse", "94", ("2A", "2B")),
        Region("guadeloupe", "Guadeloupe", "01", ("971",)),
        Region("martinique", "Martinique", "02", ("972",)),
        Region("guyane", "Guyane", "03", ("973",)),
        Region("la-reunion", "La Réunion", "04", ("974",)),
        Region("mayotte", "Mayotte", "06", ("976",)),
    ]
}

ALIAS_REGIONS = {
    "idf": "ile-de-france",
    "paris": "ile-de-france",
    "hdf": "hauts-de-france",
    "nord": "hauts-de-france",
    "paca": "provence-alpes-cote-d-azur",
    "sud": "provence-alpes-cote-d-azur",
    "aura": "auvergne-rhone-alpes",
    "reunion": "la-reunion",
    "bfc": "bourgogne-franche-comte",
}


def trouver_region(valeur: str) -> Region:
    """Accepte une clé ('hauts-de-france'), un nom ('Hauts de France'), un alias ('idf') ou un code ('32')."""
    cle = normaliser(valeur).replace(" ", "-")
    cle = ALIAS_REGIONS.get(cle, cle)
    if cle in REGIONS:
        return REGIONS[cle]
    for region in REGIONS.values():
        if valeur.strip() == region.code or normaliser(region.nom).replace(" ", "-") == cle:
            return region
    connues = ", ".join(REGIONS)
    raise ValueError(f"Région inconnue : {valeur!r}. Valeurs possibles : {connues}")


# --------------------------------------------------------------------------- #
# Codes NAF (activité principale) des entreprises qui recrutent des profils IT
# --------------------------------------------------------------------------- #

NAF = {
    "62.01Z": "Programmation informatique",
    "62.02A": "Conseil en systèmes et logiciels informatiques",
    "62.02B": "Tierce maintenance de systèmes et d'applications informatiques",
    "62.03Z": "Gestion d'installations informatiques",
    "62.09Z": "Autres activités informatiques",
    "63.11Z": "Traitement de données, hébergement et activités connexes",
    "63.12Z": "Portails Internet",
    "58.29A": "Édition de logiciels système et de réseau",
    "58.29B": "Édition de logiciels outils de développement et de langages",
    "58.29C": "Édition de logiciels applicatifs",
    "61.10Z": "Télécommunications filaires",
    "61.20Z": "Télécommunications sans fil",
    "61.90Z": "Autres activités de télécommunication",
    "95.11Z": "Réparation d'ordinateurs et d'équipements périphériques",
    "46.51Z": "Commerce de gros d'ordinateurs, d'équipements informatiques et de logiciels",
    "80.20Z": "Activités liées aux systèmes de sécurité",
}

# Formulation utilisée dans la lettre selon le secteur de l'entreprise.
SECTEURS_NAF = {
    "62.01Z": "le développement de solutions logicielles",
    "62.02A": "le conseil et l'accompagnement informatique",
    "62.02B": "l'infogérance et la maintenance des systèmes d'information",
    "62.03Z": "l'exploitation et la gestion d'infrastructures informatiques",
    "62.09Z": "les services informatiques",
    "63.11Z": "l'hébergement et le traitement de données",
    "63.12Z": "les services numériques",
    "58.29A": "l'édition de logiciels système et réseau",
    "58.29B": "l'édition d'outils de développement",
    "58.29C": "l'édition de logiciels",
    "61.10Z": "les télécommunications",
    "61.20Z": "les télécommunications",
    "61.90Z": "les télécommunications",
    "95.11Z": "la maintenance de matériel informatique",
    "46.51Z": "la distribution de solutions informatiques",
    "80.20Z": "la sécurité des systèmes",
}


# --------------------------------------------------------------------------- #
# Tranches d'effectif salarié (codes INSEE)
# --------------------------------------------------------------------------- #

# code -> (borne basse, libellé)
TRANCHES_EFFECTIF = {
    "00": (0, "0 salarié"),
    "01": (1, "1 ou 2 salariés"),
    "02": (3, "3 à 5 salariés"),
    "03": (6, "6 à 9 salariés"),
    "11": (10, "10 à 19 salariés"),
    "12": (20, "20 à 49 salariés"),
    "21": (50, "50 à 99 salariés"),
    "22": (100, "100 à 199 salariés"),
    "31": (200, "200 à 249 salariés"),
    "32": (250, "250 à 499 salariés"),
    "41": (500, "500 à 999 salariés"),
    "42": (1000, "1 000 à 1 999 salariés"),
    "51": (2000, "2 000 à 4 999 salariés"),
    "52": (5000, "5 000 à 9 999 salariés"),
    "53": (10000, "10 000 salariés et plus"),
}


def tranches_a_partir_de(effectif_min: int) -> list[str]:
    """Codes de tranches dont la borne basse est >= effectif_min."""
    return [code for code, (borne, _) in TRANCHES_EFFECTIF.items() if borne >= effectif_min]


def borne_effectif(code: str | None) -> int | None:
    if code and code in TRANCHES_EFFECTIF:
        return TRANCHES_EFFECTIF[code][0]
    return None


# --------------------------------------------------------------------------- #
# Métiers
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Metier:
    cle: str
    titre: str
    naf: tuple[str, ...]
    competences: tuple[str, ...]
    missions: tuple[str, ...]
    accroches: tuple[str, ...] = field(default_factory=tuple)
    titre_f: str = ""
    recherches: tuple[str, ...] = field(default_factory=tuple)   # requêtes envoyées aux sites d'offres
    intitules: tuple[str, ...] = field(default_factory=tuple)    # mots d'intitulé qui signalent ce métier

    def titre_pour(self, genre: str | None) -> str:
        return self.titre_f if (genre or "").upper().startswith("F") and self.titre_f else self.titre


METIERS: dict[str, Metier] = {
    m.cle: m
    for m in [
        Metier(
            cle="administrateur_reseau",
            recherches=("administrateur réseau", "ingénieur réseau", "technicien réseau"),
            intitules=("reseau", "reseaux", "network", "telecom"),
            titre_f="Administratrice réseau",
            titre="Administrateur réseau",
            naf=("62.02A", "62.02B", "62.03Z", "62.09Z", "61.10Z", "61.20Z", "61.90Z", "63.11Z"),
            competences=(
                "Cisco", "CCNA", "routage", "switching", "VLAN", "OSPF", "BGP", "TCP/IP", "DNS", "DHCP",
                "VPN", "IPsec", "pare-feu", "Fortinet", "FortiGate", "pfSense", "Stormshield", "Palo Alto",
                "Wi-Fi", "Aruba", "SD-WAN", "QoS", "Zabbix", "Nagios", "Centreon", "Wireshark", "LAN", "WAN",
            ),
            missions=(
                "l'administration et la sécurisation des équipements réseau (switchs, routeurs, pare-feu)",
                "la supervision et le diagnostic des incidents réseau",
                "le déploiement d'architectures LAN/WAN, VPN et Wi-Fi",
            ),
            accroches=(
                "[Passionné|Passionnée|Passionné(e)] par les infrastructures réseau, je souhaite mettre mes compétences "
                "d'administrateur réseau au service {de_entreprise}.",
                "Je vous adresse ma candidature spontanée pour un poste d'administrateur réseau au sein "
                "{de_entreprise}.",
                "Garantir la disponibilité et la sécurité d'un réseau est au cœur de mon métier ; c'est "
                "pourquoi je me permets de vous proposer ma candidature au sein {de_entreprise}.",
            ),
        ),
        Metier(
            cle="administrateur_systeme",
            recherches=("administrateur système", "administrateur systèmes et réseaux", "ingénieur système"),
            intitules=("systeme", "systemes", "sysadmin", "infrastructure", "exploitation"),
            titre_f="Administratrice systèmes",
            titre="Administrateur systèmes",
            naf=("62.02A", "62.02B", "62.03Z", "62.09Z", "63.11Z", "58.29A", "58.29C"),
            competences=(
                "Windows Server", "Active Directory", "GPO", "Linux", "Debian", "Ubuntu", "Red Hat", "RHEL",
                "CentOS", "VMware", "vSphere", "Hyper-V", "Proxmox", "PowerShell", "Bash", "Veeam",
                "sauvegarde", "Microsoft 365", "Office 365", "Exchange", "Entra ID", "Azure AD", "Intune",
                "DNS", "DHCP", "Zabbix", "Nagios", "Centreon", "Ansible", "ITIL", "GLPI", "SAN", "NAS",
            ),
            missions=(
                "l'administration des serveurs Windows et Linux et des environnements virtualisés",
                "la gestion des annuaires, des sauvegardes et de la supervision",
                "l'automatisation des tâches d'exploitation et le maintien en condition opérationnelle",
            ),
            accroches=(
                "[Administrateur|Administratrice|Administrateur(trice)] systèmes [motivé|motivée|motivé(e)], je souhaite rejoindre {entreprise} pour contribuer à la "
                "fiabilité de vos infrastructures.",
                "Je me permets de vous adresser ma candidature spontanée pour un poste d'administrateur "
                "systèmes au sein {de_entreprise}.",
                "Assurer la disponibilité, la sécurité et la performance des systèmes est ce qui m'anime "
                "au quotidien ; je serais [heureux|heureuse] de le faire pour {entreprise}.",
            ),
        ),
        Metier(
            cle="technicien_informatique",
            recherches=("technicien informatique", "technicien support", "technicien helpdesk"),
            intitules=("technicien", "support", "helpdesk", "help desk", "proximite", "deploiement"),
            titre_f="Technicienne informatique",
            titre="Technicien informatique",
            naf=("62.02A", "62.02B", "62.03Z", "62.09Z", "95.11Z", "46.51Z"),
            competences=(
                "support", "helpdesk", "N1", "N2", "GLPI", "ITIL", "ticketing", "ServiceNow",
                "Windows 10", "Windows 11", "Office 365", "Microsoft 365", "Active Directory", "SCCM",
                "Intune", "masterisation", "déploiement de postes", "imprimantes", "maintenance",
                "dépannage", "TCP/IP", "Wi-Fi", "Teams", "Outlook",
            ),
            missions=(
                "le support utilisateurs de niveau 1 et 2 et la résolution des incidents",
                "la préparation, le déploiement et la maintenance des postes de travail",
                "le suivi des tickets et la documentation des procédures",
            ),
            accroches=(
                "[Technicien|Technicienne|Technicien(ne)] informatique [rigoureux|rigoureuse] et à l'écoute des utilisateurs, je souhaite "
                "rejoindre les équipes {de_entreprise}.",
                "Je vous propose ma candidature spontanée pour un poste de technicien informatique au "
                "sein {de_entreprise}.",
                "Accompagner les utilisateurs et résoudre efficacement leurs incidents est ma priorité ; "
                "je serais [ravi|ravie|ravi(e)] de mettre ce savoir-faire au service {de_entreprise}.",
            ),
        ),
        Metier(
            cle="devops",
            recherches=("devops", "ingénieur cloud", "SRE"),
            intitules=("devops", "cloud", "sre", "devsecops", "plateforme"),
            titre_f="Ingénieure DevOps",
            titre="Ingénieur DevOps",
            naf=("62.01Z", "62.02A", "62.03Z", "62.09Z", "63.11Z", "58.29A", "58.29B", "58.29C"),
            competences=(
                "Docker", "Kubernetes", "Helm", "Terraform", "Ansible", "CI/CD", "GitLab CI",
                "GitHub Actions", "Jenkins", "ArgoCD", "Git", "AWS", "Azure", "GCP", "OpenStack",
                "Prometheus", "Grafana", "ELK", "Python", "Bash", "Linux", "Nginx", "Vault", "SonarQube",
            ),
            missions=(
                "l'industrialisation des déploiements via des pipelines CI/CD",
                "la conteneurisation et l'orchestration des applications (Docker, Kubernetes)",
                "l'Infrastructure as Code et l'observabilité des plateformes",
            ),
            accroches=(
                "[Ingénieur|Ingénieure|Ingénieur(e)] DevOps [passionné|passionnée|passionné(e)] par l'automatisation, je souhaite contribuer à "
                "l'industrialisation des plateformes {de_entreprise}.",
                "Je vous adresse ma candidature spontanée pour un poste d'ingénieur DevOps au sein "
                "{de_entreprise}.",
                "Rapprocher développement et exploitation pour livrer plus vite et plus sûrement : c'est "
                "l'approche que je souhaite apporter à {entreprise}.",
            ),
        ),
        Metier(
            cle="cybersecurite",
            recherches=("cybersécurité", "analyste SOC", "ingénieur sécurité"),
            intitules=("securite", "cyber", "soc", "pentest", "rssi"),
            titre_f="Analyste cybersécurité",
            titre="Analyste cybersécurité",
            naf=("62.02A", "62.03Z", "62.09Z", "63.11Z", "58.29A", "80.20Z"),
            competences=(
                "SOC", "SIEM", "Splunk", "QRadar", "EDR", "pentest", "ISO 27001", "EBIOS", "ANSSI",
                "RGPD", "IAM", "pare-feu", "Fortinet", "Kali", "Burp", "OWASP", "durcissement",
                "gestion des vulnérabilités", "Nessus", "CrowdStrike",
            ),
            missions=(
                "la détection et le traitement des incidents de sécurité",
                "l'analyse des vulnérabilités et le durcissement des systèmes",
                "la sensibilisation des utilisateurs et la conformité (ISO 27001, RGPD)",
            ),
            accroches=(
                "[Passionné|Passionnée|Passionné(e)] par la sécurité des systèmes d'information, je souhaite rejoindre "
                "{entreprise} pour renforcer la protection de vos infrastructures.",
                "Je vous adresse ma candidature spontanée pour un poste en cybersécurité au sein "
                "{de_entreprise}.",
            ),
        ),
        Metier(
            cle="developpeur",
            recherches=("développeur", "développeur web", "développeur Python"),
            intitules=("developpeur", "developpeuse", "developer", "dev ", "fullstack", "backend", "frontend"),
            titre_f="Développeuse",
            titre="Développeur",
            naf=("62.01Z", "62.02A", "62.09Z", "58.29B", "58.29C", "63.12Z"),
            competences=(
                "Python", "Java", "JavaScript", "TypeScript", "PHP", "C#", ".NET", "React", "Angular",
                "Vue.js", "Node.js", "Django", "Symfony", "Spring", "SQL", "PostgreSQL", "MySQL",
                "MongoDB", "API REST", "Git", "Docker", "tests unitaires", "Agile", "Scrum",
            ),
            missions=(
                "la conception et le développement de nouvelles fonctionnalités",
                "la maintenance évolutive et corrective des applications",
                "l'écriture de tests et la revue de code",
            ),
            accroches=(
                "[Développeur|Développeuse] [motivé|motivée|[motivé|motivée|motivé(e)]], je souhaite mettre mes compétences au service des projets "
                "{de_entreprise}.",
                "Je vous adresse ma candidature spontanée pour un poste de développeur au sein "
                "{de_entreprise}.",
            ),
        ),
    ]
}

ALIAS_METIERS = {
    "reseau": "administrateur_reseau",
    "admin reseau": "administrateur_reseau",
    "administrateur reseau": "administrateur_reseau",
    "administrateur reseaux": "administrateur_reseau",
    "systeme": "administrateur_systeme",
    "admin sys": "administrateur_systeme",
    "adminsys": "administrateur_systeme",
    "sysadmin": "administrateur_systeme",
    "administrateur systeme": "administrateur_systeme",
    "administrateur systemes": "administrateur_systeme",
    "technicien": "technicien_informatique",
    "technicien informatique": "technicien_informatique",
    "support": "technicien_informatique",
    "helpdesk": "technicien_informatique",
    "dev ops": "devops",
    "ingenieur devops": "devops",
    "cyber": "cybersecurite",
    "securite": "cybersecurite",
    "dev": "developpeur",
    "developpeur": "developpeur",
}


def trouver_metier(valeur: str) -> Metier:
    cle = normaliser(valeur)
    cle = ALIAS_METIERS.get(cle, cle).replace(" ", "_")
    if cle in METIERS:
        return METIERS[cle]
    connus = ", ".join(METIERS)
    raise ValueError(f"Métier inconnu : {valeur!r}. Valeurs possibles : {connus}")


def toutes_les_competences() -> list[str]:
    vues: dict[str, str] = {}
    for metier in METIERS.values():
        for comp in metier.competences:
            vues.setdefault(normaliser(comp), comp)
    return list(vues.values())


# --------------------------------------------------------------------------- #
# Types de contrat
# --------------------------------------------------------------------------- #

CONTRATS = {
    "CDI": "CDI",
    "CDD": "CDD",
    "interim": "intérim",
    "alternance": "alternance",
    "stage": "stage",
    "freelance": "freelance",
}

_ALIAS_CONTRATS = {
    "cdi": "CDI", "permanent": "CDI", "contrat a duree indeterminee": "CDI",
    "cdd": "CDD", "contract": "CDD", "contrat a duree determinee": "CDD", "temporary": "CDD",
    "mis": "interim", "interim": "interim", "travail temporaire": "interim", "mission interimaire": "interim",
    "alternance": "alternance", "apprentissage": "alternance", "contrat d apprentissage": "alternance",
    "professionnalisation": "alternance", "contrat de professionnalisation": "alternance", "apprenti": "alternance",
    "stage": "stage", "stagiaire": "stage", "intern": "stage", "internship": "stage",
    "lib": "freelance", "freelance": "freelance", "independant": "freelance", "contractor": "freelance",
    "profession liberale": "freelance", "portage salarial": "freelance",
}


def normaliser_contrat(valeur: str | None) -> str | None:
    """'cdi', 'Contrat à durée indéterminée', 'permanent' -> 'CDI' ; None si inconnu."""
    if not valeur:
        return None
    cle = normaliser(valeur)
    if cle in _ALIAS_CONTRATS:
        return _ALIAS_CONTRATS[cle]
    for alias, canonique in _ALIAS_CONTRATS.items():
        if cle.startswith(alias + " ") or f" {alias} " in f" {cle} ":
            return canonique
    return None


def contrats_valides(valeurs) -> list[str]:
    """Normalise une liste de types de contrat et lève une erreur claire sur une valeur inconnue."""
    resultat: list[str] = []
    for valeur in valeurs or []:
        canonique = normaliser_contrat(str(valeur))
        if not canonique:
            raise ValueError(f"Type de contrat inconnu : {valeur!r}. Valeurs possibles : {', '.join(CONTRATS)}")
        if canonique not in resultat:
            resultat.append(canonique)
    return resultat


def libelle_contrats(contrats: list[str]) -> str:
    """['CDI', 'CDD'] -> 'CDI ou CDD'."""
    libelles = [CONTRATS.get(c, c) for c in contrats]
    if len(libelles) <= 1:
        return "".join(libelles)
    return ", ".join(libelles[:-1]) + " ou " + libelles[-1]
