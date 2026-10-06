# Guide d'utilisation

Ce guide vous accompagne de l'installation au premier envoi. Comptez 15 minutes.

## 1. Installation

```bash
python --version                   # 3.10 minimum
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell) : .venv\Scripts\Activate.ps1
pip install -e ".[dns]"            # ".[dns,ia]" pour activer la rédaction par l'IA
```

`dns` permet de vérifier qu'un domaine accepte bien des e-mails (enregistrement MX) avant d'écrire.

## 2. Initialisation

```bash
autopostule init
```

Cela crée :

| Fichier / dossier | Rôle                                                                 |
|-------------------|----------------------------------------------------------------------|
| `config.yaml`     | votre profil, vos critères de recherche, vos réglages d'envoi        |
| `.env`            | vos secrets (mot de passe SMTP, clé API) - **ne le partagez jamais** |
| `cv/`             | déposez-y votre CV (PDF conseillé)                                   |
| `donnees/`        | créé au premier lancement : base SQLite, lettres, journaux d'envoi    |

## 3. Renseigner votre profil

Dans `config.yaml`, section `profil` : prénom, nom, e-mail, téléphone, ville, titre, années d'expérience,
type de contrat recherché, disponibilité. Ces informations apparaissent dans l'en-tête de la lettre,
dans l'objet du mail et dans la signature.

`genre` (`M`, `F` ou vide) sert aux accords : « motivé / motivée », « Technicien / Technicienne »…
Laissé vide, la lettre utilise l'écriture inclusive (« motivé(e) »).

Indiquez ensuite le chemin du CV (`cv.fichier`) et vérifiez l'analyse :

```bash
autopostule cv
```

```
CV : cv/mon_cv.pdf  (3412 caractères extraits)
E-mail détecté    : jean.dupont@mail.fr
Téléphone détecté : 06 12 34 56 78
Compétences reconnues (17) :
  Windows Server, Active Directory, GPO, Linux, Debian, VMware, Proxmox, PowerShell, ...
Adéquation par métier :
  Administrateur systèmes      ███████████ 11
  Administrateur réseau        ████ 4
  ...
```

Les compétences reconnues pour le métier visé sont citées dans chaque lettre. Si une compétence importante
n'est pas détectée, vérifiez qu'elle est écrite telle quelle dans votre CV (la liste est dans
`autopostule/referentiel.py`, vous pouvez la compléter).

## 4. Configurer l'envoi des e-mails

Les candidatures partent **de votre propre boîte mail**, ce qui permet aux recruteurs de vous répondre
directement et d'avoir un historique dans vos « Envoyés ».

### Gmail

1. Activez la validation en deux étapes sur votre compte Google.
2. Créez un mot de passe d'application : <https://myaccount.google.com/apppasswords>.
3. Dans `config.yaml` :
   ```yaml
   envoi:
     smtp_hote: "smtp.gmail.com"
     smtp_port: 587
     securite: "starttls"
     smtp_utilisateur: "votre.adresse@gmail.com"
   ```
4. Dans `.env` : `AUTOPOSTULE_SMTP_PASSWORD=le-mot-de-passe-d-application`

### Outlook / Hotmail

`smtp-mail.outlook.com`, port `587`, `starttls`. Microsoft désactive progressivement l'authentification par
mot de passe : si la connexion est refusée, utilisez une autre messagerie.

### Autres fournisseurs

| Fournisseur  | Hôte                | Port | Sécurité |
|--------------|---------------------|------|----------|
| OVH          | `ssl0.ovh.net`      | 465  | ssl      |
| Orange       | `smtp.orange.fr`    | 465  | ssl      |
| Free         | `smtp.free.fr`      | 465  | ssl      |
| Infomaniak   | `mail.infomaniak.com` | 465 | ssl     |
| Proton (Bridge) | `127.0.0.1`      | 1025 | starttls |

## 5. Trouver des entreprises

```bash
autopostule metiers                     # liste des métiers
autopostule regions                     # liste des régions et départements

autopostule rechercher -m devops -r ile-de-france -n 100
autopostule rechercher -m administrateur_reseau -m technicien -r hauts-de-france -r normandie
autopostule rechercher -m sysadmin -d 59 -d 62 --effectif-min 20
autopostule rechercher -m technicien -r hauts-de-france -v Lille -v Roubaix -v Tourcoing
```

| Option              | Exemple             | Effet                                                    |
|---------------------|---------------------|----------------------------------------------------------|
| `-m / --metier`     | `devops`, `reseau`  | métier visé (répétable ; alias acceptés)                 |
| `-r / --region`     | `idf`, `hdf`, `paca`| région (répétable)                                        |
| `-d / --departement`| `92`                | département (prioritaire sur la région)                   |
| `-v / --ville`      | `Lille`             | commune du siège social                                   |
| `-n / --limite`     | `100`               | nombre maximum d'entreprises par métier                   |
| `--effectif-min`    | `10`                | ignore les structures plus petites                        |

Sans option, les valeurs de la section `recherche` de `config.yaml` sont utilisées.

La recherche interroge l'API officielle **Recherche d'entreprises** (base SIRENE) et sélectionne les
entreprises actives dont l'**activité principale (code NAF)** correspond au métier : ESN, infogérance,
hébergeurs, éditeurs de logiciels, opérateurs télécoms… Les entrepreneurs individuels, associations et
administrations sont écartés. Pour cibler d'autres secteurs (banque, industrie…), ajoutez leurs codes NAF dans
`recherche.naf_supplementaires`.

### Importer votre propre liste

Vous avez une liste d'entreprises (salon, annuaire, liste d'un ami) ? Importez-la en CSV
(séparateur `,` ou `;`) :

```csv
nom;site;email;ville;metier
Acme Infra;acme-infra.fr;;Lille;administrateur_systeme
Beta Cloud;https://www.betacloud.io;jobs@betacloud.io;Paris;devops
```

```bash
autopostule importer docs/exemples/entreprises.csv
```

Si l'e-mail est fourni, l'entreprise est prête ; si seul le site est fourni, `scanner` y cherchera une adresse.

## 6. Trouver les adresses de recrutement

```bash
autopostule scanner          # toutes les entreprises en attente
autopostule scanner -n 30    # par lots
```

Pour chaque entreprise :

1. **Site web** : l'outil essaie les domaines plausibles (`acmeinfra.fr`, `acme-infra.com`…) et ne garde un
   site que s'il est **vérifié** : SIREN présent sur le site (mentions légales) ou nom de l'entreprise dans le
   titre de la page.
2. **Exploration** : page d'accueil, pages « recrutement », « carrières », « nous rejoindre », « contact »,
   « mentions légales » (8 pages maximum, `robots.txt` respecté, 1,5 s entre deux requêtes).
3. **Classement des adresses** :

| Type        | Exemples                                     | Score | Utilisée par défaut |
|-------------|----------------------------------------------|-------|---------------------|
| `rh`        | recrutement@, rh@, jobs@, careers@, talents@ | 100 (+15 si page recrutement) | oui |
| `generique` | contact@, info@, hello@, accueil@            | 60    | oui                 |
| `nominatif` | prenom.nom@                                  | 40    | non (`inclure_emails_nominatifs`) |
| exclues     | noreply@, compta@, support@, dpo@, adresses d'agences web… | - | jamais |

L'adresse au meilleur score est utilisée. Une seule candidature est préparée par entreprise.

> Le site n'est pas toujours retrouvé automatiquement (noms commerciaux différents de la raison sociale).
> Comptez 30 à 50 % de réussite ; complétez avec l'import CSV.

## 7. Rédiger les lettres

```bash
autopostule generer               # moteur « modele » : gratuit, hors ligne
autopostule generer --ia          # rédaction personnalisée par Claude
autopostule generer -m devops -n 20
```

Chaque lettre est adaptée à l'entreprise :

- **accroche** propre au métier, choisie parmi plusieurs variantes ;
- **parcours** : vos années d'expérience, les missions du métier, **les compétences de votre CV** utiles pour
  ce poste ;
- **paragraphe entreprise** selon son **secteur** (ESN, infogérance, hébergeur, éditeur, télécom…), sa
  **taille** (structure à taille humaine / PME / grand groupe) et sa **proximité** avec votre domicile ;
- votre **paragraphe personnel** (`lettre.paragraphe_perso`) ;
- conclusion avec votre disponibilité.

Une même entreprise obtient toujours la même lettre ; deux entreprises différentes obtiennent des
formulations différentes.

Résultats : `donnees/lettres/*.pdf` (jointes au mail) et `*.txt`.

### Mode IA (Claude)

1. `pip install -e ".[ia]"`
2. Clé API sur <https://console.anthropic.com/>, à placer dans `.env` : `ANTHROPIC_API_KEY=...`
3. `lettre.moteur: "ia"` dans `config.yaml`, ou `--ia` en ligne de commande.

L'IA reçoit votre CV, votre profil, les informations publiques de l'entreprise et le brouillon généré par le
modèle ; elle a pour consigne de **ne rien inventer** qui ne figure pas dans votre CV. En cas d'erreur (pas de
clé, quota…), l'outil reprend automatiquement la lettre du modèle. Comptez quelques centimes par lettre.

### Personnaliser les modèles

Copiez `autopostule/templates/lettre.txt.j2` et/ou `mail.txt.j2` dans un dossier, modifiez-les, puis indiquez
ce dossier dans `lettre.dossier_modeles`. Variables disponibles : `profil.*`, `entreprise.*`
(`nom`, `nom_court`, `ville`, `adresse`, `naf`…), `titre`, `metier.*`, `date`, `corps`.

## 8. Relire et approuver

```bash
autopostule lister -s brouillon
autopostule voir 12               # message + lettre complète
autopostule ignorer 15 16         # écarter des candidatures
autopostule approuver 12 13 14    # ou : autopostule approuver --tout
```

Avec `envoi.validation_manuelle: true` (par défaut), **seules les candidatures approuvées partent**.

## 9. Envoyer

```bash
autopostule envoyer --test        # écrit des .eml dans donnees/envois_test/ (ouvrables dans votre messagerie)
autopostule envoyer               # demande confirmation, puis envoie
autopostule envoyer --max 10 -y   # 10 envois maximum, sans confirmation
```

Chaque e-mail contient : un court message, votre CV renommé proprement (`CV_jean_dupont.pdf`) et la lettre en
PDF (ou la lettre complète dans le corps si `joindre_pdf: false`).

Garde-fous :

- plafond quotidien (`max_par_jour`, 40 par défaut) ;
- délai aléatoire entre deux envois (60 à 180 s) ;
- aucune entreprise recontactée avant `delai_recontact_jours` (120 jours) ;
- adresses, domaines et SIREN de la liste d'exclusion ignorés ;
- arrêt immédiat si le serveur refuse l'authentification, et après 3 échecs consécutifs.

Relancez simplement `autopostule envoyer` chaque jour pour continuer là où vous vous êtes arrêté.

## 10. Après l'envoi

```bash
autopostule stats
autopostule exclure rh@societe.fr          # une personne vous demande de ne plus écrire
autopostule exclure societe.fr             # tout un domaine
autopostule exclure 123456789 --raison "déjà postulé via leur site"
```

Répondez rapidement aux recruteurs, et **respectez toute demande de désinscription** (cf. [LEGAL.md](LEGAL.md)).

## 11. Tout automatiser

```bash
autopostule auto -m administrateur_systeme -r hauts-de-france -n 150
autopostule auto -m devops -d 92 --ia --approuver-tout   # sans relecture : à vos risques
```

Pour lancer l'envoi chaque matin (Linux/macOS, `crontab -e`) :

```
30 8 * * 1-5 cd /chemin/vers/projet && .venv/bin/autopostule envoyer -y >> donnees/envoi.log 2>&1
```

Sous Windows : Planificateur de tâches → action `C:\chemin\.venv\Scripts\autopostule.exe envoyer -y`.

## Dépannage

| Problème                                         | Solution                                                         |
|--------------------------------------------------|------------------------------------------------------------------|
| `Mot de passe SMTP absent`                       | renseignez `AUTOPOSTULE_SMTP_PASSWORD` dans `.env`               |
| `SMTPAuthenticationError` avec Gmail             | utilisez un mot de passe d'application, pas votre mot de passe   |
| `site introuvable` pour beaucoup d'entreprises    | normal pour une partie ; complétez via `importer`               |
| aucune compétence détectée                       | CV en image (scanné) : exportez-le en PDF texte depuis Word      |
| erreur 429 de l'API                              | l'outil réessaie automatiquement ; relancez plus tard sinon      |
| les e-mails arrivent en spam                     | baissez `max_par_jour`, personnalisez la lettre, évitez les liens |
