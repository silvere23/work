# autopostule

**Automatisez vos candidatures spontanées dans l'informatique** : à partir de votre CV, l'outil trouve des
entreprises par **métier** (administrateur réseau, administrateur systèmes, technicien informatique, DevOps,
cybersécurité, développeur) et par **zone géographique** (Île-de-France, Hauts-de-France, un département,
une ville…), récupère leurs **adresses de recrutement publiques**, rédige une **lettre de motivation adaptée à
chaque entreprise** et **envoie** la candidature (CV + lettre) depuis votre propre boîte mail.

```
 CV (PDF/DOCX)          API SIRENE (data.gouv)       Sites web des entreprises
      │                          │                              │
      ▼                          ▼                              ▼
 ┌─────────┐   métier/région  ┌────────────┐  site + e-mails ┌─────────┐
 │ analyse │ ───────────────► │ rechercher │ ──────────────► │ scanner │
 └─────────┘                  └────────────┘                 └─────────┘
      │ compétences                                               │ recrutement@, rh@, jobs@…
      ▼                                                           ▼
 ┌──────────────────────┐   relecture    ┌───────────┐  SMTP  ┌─────────┐
 │ générer les lettres  │ ─────────────► │ approuver │ ─────► │ envoyer │
 │ (modèle ou IA Claude)│                └───────────┘        └─────────┘
 └──────────────────────┘
```

## Pourquoi Python ?

| Besoin                              | Ce que Python apporte                                           |
|-------------------------------------|-----------------------------------------------------------------|
| Lire un CV PDF / Word               | `pypdf`, `python-docx`                                          |
| Interroger des API et des sites web | `requests`, `BeautifulSoup`, `urllib.robotparser` (robots.txt)  |
| Rédiger des lettres                 | `Jinja2` (modèles), SDK officiel `anthropic` (IA Claude)        |
| Produire des PDF                    | `fpdf2`                                                         |
| Envoyer des e-mails                 | `smtplib` / `email` inclus dans la bibliothèque standard        |
| Suivre les candidatures             | `sqlite3` inclus : une base locale, sans serveur                |

Python est le langage de référence pour le scraping, l'automatisation et l'IA : tout tient dans un seul
langage, multiplateforme (Windows, macOS, Linux), facile à lire et à modifier même en débutant.
(Alternative possible : Node.js avec Puppeteer, mais l'écosystème PDF/IA/scraping y est moins direct.)

## Installation

Prérequis : **Python 3.10 ou plus récent**.

```bash
git clone <ce-depot> && cd work
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -e ".[dns]"            # ajoutez ",ia" pour les lettres rédigées par Claude : ".[dns,ia]"
```

## Démarrage rapide

```bash
autopostule init                   # crée config.yaml, .env et le dossier cv/
# 1) copiez votre CV dans cv/ et remplissez config.yaml (nom, téléphone, e-mail, métier, région…)
# 2) mettez votre mot de passe d'application SMTP dans .env
autopostule cv                     # vérifie ce que l'outil comprend de votre CV

autopostule rechercher -m devops -r ile-de-france -n 100
autopostule scanner                # trouve les sites et les adresses RH
autopostule generer                # une lettre personnalisée par entreprise
autopostule lister -s brouillon    # relecture
autopostule voir 12
autopostule approuver --tout
autopostule envoyer --test         # simulation : fichiers .eml, rien n'est envoyé
autopostule envoyer                # envoi réel (40/jour max par défaut)
```

Ou tout en une commande :

```bash
autopostule auto -m administrateur_systeme -r hauts-de-france -n 150
```

## Documentation

| Document                                       | Contenu                                                     |
|------------------------------------------------|-------------------------------------------------------------|
| [docs/GUIDE.md](docs/GUIDE.md)                 | Guide pas à pas, toutes les commandes, configuration Gmail/Outlook, exemples |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Référence complète de `config.yaml`                         |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)   | Fonctionnement interne, modules, base de données, extension |
| [docs/LEGAL.md](docs/LEGAL.md)                 | RGPD, CNIL, bonnes pratiques d'envoi : à lire avant d'envoyer |

## Ce que fait (et ne fait pas) l'outil

- ✅ Sources publiques et légales : base SIRENE (API officielle) et pages publiques des sites d'entreprises,
  en respectant `robots.txt` et avec un délai entre les requêtes.
- ✅ Priorité aux adresses **génériques de recrutement** (`recrutement@`, `rh@`, `jobs@`, `careers@`…),
  puis `contact@`. Les adresses nominatives (`prenom.nom@`) sont **désactivées par défaut** (RGPD).
- ✅ Lettres différentes d'une entreprise à l'autre : secteur d'activité, taille, ville, compétences de votre CV
  correspondant au métier visé, formulations variées ; option IA (Claude) pour une personnalisation poussée.
- ✅ Garde-fous : validation manuelle, plafond quotidien, délais aléatoires, mode test, pas de double envoi,
  liste d'exclusion (`autopostule exclure`), arrêt automatique en cas d'erreurs SMTP.
- ❌ Pas de scraping de LinkedIn, Indeed, Welcome to the Jungle… (interdit par leurs conditions d'utilisation).
- ❌ Ne remplit pas les formulaires de candidature des sites carrière.

## Tests

```bash
pip install -e ".[dev,ia]"
pytest
```

Les tests utilisent un faux site d'entreprise, une fausse API SIRENE, un faux serveur SMTP et un faux serveur
Claude : aucun réseau ni aucune clé ne sont nécessaires.

## Licence

MIT.
