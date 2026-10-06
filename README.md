# autopostule

**Automatisez vos candidatures dans l'informatique**, sur deux fronts :

1. **Offres d'emploi récentes** : l'outil récupère les offres publiées ces derniers jours (France Travail et
   ses sites partenaires, Adzuna qui agrège de nombreux sites emploi, plus toute offre que vous ajoutez depuis
   LinkedIn, Indeed, un site carrière…), filtrées par **métier**, **zone géographique** et **type de contrat**
   (CDI, CDD, intérim, alternance, stage, freelance).
2. **Candidatures spontanées** : il trouve des entreprises par métier et par zone (base SIRENE) et récupère
   leurs **adresses de recrutement publiques**.

Pour **chaque** candidature, il produit un **CV adapté au poste** (titre = intitulé de l'offre, compétences
demandées mises en avant, missions réordonnées) et une **lettre de motivation** qui répond à l'offre ou à
l'entreprise, puis **envoie** le tout par e-mail depuis votre boîte, ou prépare le dossier quand l'offre ne
se postule que sur un site.

```
 Offres récentes                     Entreprises (SIRENE)
 France Travail · Adzuna · vos liens       │
        │                                  ▼
        │                        site web → recrutement@, rh@, jobs@…
        ▼                                  │
 ┌───────────────────────────────────────────────────────────┐
 │ pour chaque cible : CV adapté (PDF) + lettre adaptée (PDF)  │  ← cv.yaml + config.yaml
 └───────────────────────────────────────────────────────────┘
        │ e-mail connu ?                    
   oui  ▼                          non ▼
 relecture → envoi SMTP        dossier prêt + lien de l'offre (dépôt sur le site)
```

## Pourquoi Python ?

| Besoin                              | Ce que Python apporte                                           |
|-------------------------------------|-----------------------------------------------------------------|
| Lire un CV PDF / Word               | `pypdf`, `python-docx`                                          |
| Interroger des API et des sites web | `requests`, `BeautifulSoup`, `urllib.robotparser` (robots.txt)  |
| Rédiger lettres et CV               | `Jinja2` (modèles), SDK officiel `anthropic` (IA Claude)        |
| Produire des PDF                    | `fpdf2`                                                         |
| Envoyer des e-mails                 | `smtplib` / `email` inclus dans la bibliothèque standard        |
| Suivre les candidatures             | `sqlite3` inclus : une base locale, sans serveur                |

Python est le langage de référence pour le scraping, l'automatisation et l'IA : tout tient dans un seul
langage, multiplateforme (Windows, macOS, Linux), facile à lire et à modifier.

## Installation

Prérequis : **Python 3.10 ou plus récent**.

```bash
git clone <ce-depot> && cd work
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dns]"            # ajoutez ",ia" pour la rédaction par Claude : ".[dns,ia]"
```

## Démarrage rapide

```bash
autopostule init                   # crée config.yaml, .env et le dossier cv/
# 1) copiez votre CV dans cv/, remplissez config.yaml (identité, métier, région, types_contrat)
# 2) dans .env : mot de passe SMTP + identifiants gratuits France Travail / Adzuna
autopostule cv                     # ce que l'outil comprend de votre CV
autopostule cv-structure           # crée cv/cv.yaml : complétez-le (base des CV adaptés)

# Offres récentes
autopostule offres rechercher -m sysadmin -r hauts-de-france -t CDI -t CDD
autopostule offres ajouter --url https://www.exemple.fr/offre/123      # ou --fichier offre_linkedin.txt
autopostule offres preparer        # CV + lettre adaptés à chaque offre, recherche de l'e-mail RH

# Candidatures spontanées
autopostule rechercher -m devops -r ile-de-france -n 100
autopostule scanner
autopostule generer -t CDI

# Relecture puis envoi
autopostule lister -s brouillon && autopostule voir 12
autopostule approuver --tout
autopostule envoyer --test         # simulation : fichiers .eml
autopostule envoyer                # envoi réel (40/jour max par défaut)
autopostule offres lister -s a_postuler_sur_site   # offres à déposer sur leur site (dossier prêt)
```

Ou tout en une commande :

```bash
autopostule auto -m administrateur_systeme -r hauts-de-france -t CDI
```

## Documentation

| Document                                       | Contenu                                                     |
|------------------------------------------------|-------------------------------------------------------------|
| [docs/GUIDE.md](docs/GUIDE.md)                 | Guide pas à pas : clés API, offres, CV adapté, envoi, Gmail/Outlook |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Référence complète de `config.yaml`, `cv.yaml` et `.env`   |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)   | Fonctionnement interne, modules, base de données, extension |
| [docs/LEGAL.md](docs/LEGAL.md)                 | RGPD, CNIL, plateformes, bonnes pratiques : à lire avant d'envoyer |

## Ce que fait (et ne fait pas) l'outil

- ✅ **Offres récentes** via les **API officielles** France Travail (offres déposées + sites partenaires) et
  Adzuna (agrégateur de sites emploi et pages carrières), filtrées par métier, zone, ancienneté et contrat.
- ✅ **Offres LinkedIn, Indeed, Welcome to the Jungle…** : ajoutez-les par lien (si le site autorise la
  lecture automatique) ou par copier-coller du texte (`offres ajouter --fichier`) ; elles reçoivent le même
  traitement (CV + lettre adaptés).
- ✅ **CV adapté à chaque offre** : titre du poste visé, compétences demandées en tête et en gras, missions
  les plus pertinentes en premier ; les compétences demandées que vous n'avez pas sont **signalées, jamais
  ajoutées**.
- ✅ **Lettre adaptée** : intitulé et référence de l'offre, compétences demandées que vous possédez, vos vraies
  réalisations, type de contrat, proximité géographique ; option IA (Claude).
- ✅ **Envoi automatique** quand une adresse de candidature est connue (indiquée dans l'offre, ou adresse RH
  publique retrouvée sur le site de l'entreprise) ; sinon dossier prêt + ouverture du lien.
- ✅ Garde-fous : validation manuelle, plafond quotidien, délais aléatoires, mode test, pas de double envoi,
  liste d'exclusion, arrêt automatique en cas d'erreurs SMTP.
- ❌ **Pas de robot sur LinkedIn / Indeed** (ni extraction automatique, ni dépôt automatique de candidatures
  via leurs formulaires) : leurs conditions d'utilisation l'interdisent, ils détectent ces robots et
  suspendent les comptes concernés. Voir [docs/LEGAL.md](docs/LEGAL.md).

## Tests

```bash
pip install -e ".[dev,ia]"
pytest
```

Les tests utilisent de faux serveurs (site d'entreprise, API SIRENE, France Travail, Adzuna, SMTP, Claude) :
aucun réseau ni aucune clé ne sont nécessaires.

## Licence

MIT.
