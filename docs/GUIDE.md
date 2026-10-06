# Guide d'utilisation

Ce guide vous accompagne de l'installation au premier envoi. Comptez 30 minutes, dont la création des
identifiants gratuits des sites d'offres.

## 1. Installation

```bash
python --version                   # 3.10 minimum
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell) : .venv\Scripts\Activate.ps1
pip install -e ".[dns]"            # ".[dns,ia]" pour activer la rédaction par l'IA
```

`dns` permet de vérifier qu'un domaine accepte bien des e-mails (enregistrement MX) avant d'écrire.

### Sous Windows (PowerShell)

```powershell
winget install Python.Python.3.13          # ou l'installateur de python.org, case « Add python.exe to PATH » cochée
# fermez puis rouvrez PowerShell
cd C:\Users\vous\work
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m venv .venv   # ou : python -m venv .venv
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # une seule fois, autorise l'activation
.venv\Scripts\Activate.ps1                            # « (.venv) » apparaît en début de ligne
pip install -e ".[dns,dev]"
pytest
```

| Problème Windows                                         | Solution                                                    |
|----------------------------------------------------------|-------------------------------------------------------------|
| `Python est introuvable ; exécutez sans arguments…`      | Python absent du PATH : utilisez le chemin complet ci-dessus, ou désactivez les alias `python.exe` / `python3.exe` (Paramètres → Applications → Paramètres avancés → Alias d'exécution d'application) |
| `l'exécution de scripts est désactivée sur ce système`   | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, ou utilisez `cmd` puis `.venv\Scripts\activate.bat` |
| `source` n'est pas reconnu                               | commande Linux/macOS : sous Windows, `.venv\Scripts\Activate.ps1` |
| `config.yaml … est mal écrit` avec un chemin `C:\…`      | chemin entre guillemets simples `'C:\Users\vous\Downloads\cv.pdf'`, ou copiez le CV dans `cv\` |

À chaque nouvelle fenêtre PowerShell : `cd` dans le dossier du projet puis `.venv\Scripts\Activate.ps1`.
Le dossier « Téléchargements » de l'Explorateur s'appelle en réalité `C:\Users\vous\Downloads`.

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
disponibilité. Ces informations apparaissent dans l'en-tête de la lettre,
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

## 5. Type de poste recherché (CDI, CDD…)

Dans `config.yaml` :

```yaml
recherche:
  types_contrat: ["CDI", "CDD"]   # CDI, CDD, interim, alternance, stage, freelance
```

Ce champ :

- **filtre les offres** : seules les offres de ces types sont gardées (paramètre envoyé à France Travail et
  Adzuna quand c'est possible, puis vérification locale) ;
- **apparaît dans les candidatures spontanées** : « Objet : Candidature spontanée - Ingénieur DevOps
  (CDI ou CDD) », « … pour un poste d'ingénieur DevOps en CDI ou CDD » ;
- pour une offre, c'est **le contrat de l'offre** qui est repris dans la lettre et le message.

Il se remplace ponctuellement en ligne de commande avec `-t` / `--contrat` (répétable) :

```bash
autopostule offres rechercher -t alternance
autopostule generer -t CDI -t CDD
autopostule auto -t CDD
```

Liste vide = tous types de contrat.

## 6. CV adapté à chaque candidature

L'outil peut produire **un CV PDF différent pour chaque offre ou entreprise**. Il a besoin pour cela d'un
CV structuré, `cv/cv.yaml`, qui décrit **tout** votre parcours :

```bash
autopostule cv-structure      # crée cv/cv.yaml à partir de votre CV (compétences pré-remplies)
```

Ouvrez `cv/cv.yaml` et complétez-le : titre, accroche, compétences par catégorie, expériences (poste,
entreprise, lieu, dates, **missions**), formations, certifications, langues. Plus il est complet, mieux
l'outil peut choisir ce qui correspond à chaque offre. Un exemple commenté :
`autopostule/templates/cv.exemple.yaml`.

Pour chaque candidature, le CV généré :

| Élément       | Adaptation                                                                       |
|---------------|----------------------------------------------------------------------------------|
| Titre         | intitulé de l'offre sans « H/F » (`cv_adapte.titre_selon_offre`) ; métier visé pour une candidature spontanée |
| Accroche      | votre accroche + « Atouts pour ce poste : … » (ou réécrite par Claude si `cv_adapte.moteur: ia`) |
| Compétences   | celles demandées par l'offre en premier et **en gras** ; catégories les plus utiles en tête |
| Expériences   | ordre chronologique conservé ; dans chaque poste, missions les plus pertinentes d'abord |
| Coordonnées   | depuis `config.yaml` (téléphone, e-mail, ville, LinkedIn, GitHub, permis, disponibilité) |

L'outil **n'ajoute jamais** une compétence que vous n'avez pas : celles que l'offre demande et qui manquent
à votre CV sont simplement listées pour vous (`autopostule offres voir ID`, fichier `offre.txt` du dossier).

Aperçu du CV adapté à une offre :

```bash
autopostule offres voir ft:190XKZB --apercu
```

Sans `cv.yaml`, votre CV d'origine est joint tel quel (renommé `CV_prenom_nom.pdf`).

## 7. Offres d'emploi récentes

### 7.1 Identifiants des sources (gratuits)

**France Travail** (offres déposées chez France Travail et offres de nombreux sites emploi partenaires) :

1. Créez un compte sur <https://francetravail.io> (espace « Développeur / Partenaire »).
2. Créez une application et abonnez-la à l'API **« Offres d'emploi v2 »**.
3. Copiez l'identifiant client et la clé secrète dans `.env` :
   ```
   FRANCE_TRAVAIL_CLIENT_ID=...
   FRANCE_TRAVAIL_CLIENT_SECRET=...
   ```

**Adzuna** (agrégateur de sites emploi et pages carrières) :

1. Inscrivez-vous sur <https://developer.adzuna.com>.
2. Copiez `Application ID` et `Application Key` dans `.env` :
   ```
   ADZUNA_APP_ID=...
   ADZUNA_APP_KEY=...
   ```

Une source sans identifiants est simplement ignorée. Choix des sources : `offres.sources` dans
`config.yaml`, ou `--source france_travail` en ligne de commande.

### 7.2 Rechercher

```bash
autopostule offres rechercher                                   # critères de config.yaml
autopostule offres rechercher -m devops -r ile-de-france -t CDI -j 3
autopostule offres rechercher -m technicien -d 59 -d 62 -t CDD -t interim
autopostule offres rechercher -m reseau -r hauts-de-france -v Lille
```

| Option        | Effet                                                         |
|---------------|---------------------------------------------------------------|
| `-m`          | métier (requêtes adaptées : « administrateur réseau », « ingénieur réseau »…) |
| `-r / -d / -v`| région, département, ville                                    |
| `-t`          | type(s) de contrat                                            |
| `-j`          | offres publiées depuis N jours (défaut : 7)                   |
| `-n`          | nombre maximum d'offres par métier et par source              |

Les offres hors sujet (intitulé et compétences sans rapport avec le métier) et les doublons (même offre
publiée sur plusieurs sources) sont écartés.

### 7.3 Ajouter une offre vue sur LinkedIn, Indeed, un site carrière…

```bash
# par lien : lecture automatique si le site l'autorise (données « JobPosting » publiées par la plupart des sites)
autopostule offres ajouter --url https://www.exemple-entreprise.fr/carrieres/admin-sys

# par copier-coller : collez le texte de l'offre dans un fichier
autopostule offres ajouter --fichier offre.txt --entreprise "Cloudy" --ville Lille --contrat CDI
autopostule offres ajouter --fichier offre.txt --email recrutement@cloudy.io
```

LinkedIn et Indeed interdisent la lecture automatique : utilisez `--fichier`. L'adresse e-mail éventuellement
présente dans le texte est détectée automatiquement.

### 7.4 Préparer les candidatures

```bash
autopostule offres preparer          # toutes les nouvelles offres
autopostule offres preparer --ia     # lettres rédigées par Claude
```

Pour chaque offre :

1. **adresse de candidature** : celle indiquée dans l'offre ; sinon (si `offres.chercher_email_rh: true`)
   l'entreprise est retrouvée dans la base SIRENE puis son adresse RH publique sur son site ;
2. **CV adapté** + **lettre adaptée** (intitulé, référence, compétences demandées que vous avez, vos
   réalisations les plus proches, contrat) dans `donnees/offres/<id>/` ;
3. avec une adresse : une candidature « brouillon » est créée → `approuver` puis `envoyer` ;
   sans adresse : l'offre passe au statut `a_postuler_sur_site`, le dossier est prêt.

### 7.5 Offres à déposer sur le site

```bash
autopostule offres lister -s a_postuler_sur_site
autopostule offres ouvrir ft:190XKZB      # ouvre l'offre dans le navigateur + chemin du dossier (CV, lettre)
autopostule offres fait ft:190XKZB        # une fois la candidature déposée
autopostule offres ignorer ft:190XKZB
```

Le dépôt sur le site reste manuel : les formulaires (LinkedIn, Indeed, Workday, Taleo…) demandent un compte,
des captchas et des questions propres à chaque offre, et leur automatisation est interdite par ces plateformes.
Le dossier généré (CV + lettre adaptés) rend ce dépôt rapide.

### 7.6 Suivi

```bash
autopostule offres lister                 # toutes les offres et leur statut
autopostule offres voir ft:190XKZB        # détail, compétences demandées présentes / absentes
autopostule stats
```

| Statut                 | Signification                                         |
|------------------------|-------------------------------------------------------|
| `nouvelle`             | récupérée, pas encore préparée                        |
| `preparee`             | candidature par e-mail prête (voir `lister`)          |
| `postulee`             | candidature envoyée par e-mail                        |
| `a_postuler_sur_site`  | dossier prêt, à déposer sur le site de l'offre        |
| `postulee_sur_site`    | déposée par vous sur le site                          |
| `ignoree`              | écartée                                               |

## 8. Candidatures spontanées : trouver des entreprises

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

## 9. Candidatures spontanées : trouver les adresses de recrutement

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
> Une partie des sites ne sera donc pas trouvée ; complétez avec l'import CSV.

## 10. Rédiger les lettres

```bash
autopostule generer               # moteur « modele » : gratuit, hors ligne ; CV adapté au métier si cv.yaml
autopostule generer -t CDI -t CDD # précise le type de poste dans l'objet et le message
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

## 11. Relire et approuver

```bash
autopostule lister -s brouillon
autopostule voir 12               # message + lettre complète
autopostule ignorer 15 16         # écarter des candidatures
autopostule approuver 12 13 14    # ou : autopostule approuver --tout
```

Avec `envoi.validation_manuelle: true` (par défaut), **seules les candidatures approuvées partent**.

## 12. Envoyer

```bash
autopostule envoyer --test        # écrit des .eml dans donnees/envois_test/ (ouvrables dans votre messagerie)
autopostule envoyer               # demande confirmation, puis envoie
autopostule envoyer --max 10 -y   # 10 envois maximum, sans confirmation
```

Chaque e-mail contient : un court message, **le CV adapté** à cette candidature (ou votre CV d'origine renommé
`CV_jean_dupont.pdf` sans `cv.yaml`) et la lettre en PDF (ou la lettre complète dans le corps si
`joindre_pdf: false`).

Garde-fous :

- plafond quotidien (`max_par_jour`, 40 par défaut) ;
- délai aléatoire entre deux envois (60 à 180 s) ;
- aucune entreprise recontactée en candidature spontanée avant `delai_recontact_jours` (120 jours) ;
- une seule candidature par offre ;
- adresses, domaines et SIREN de la liste d'exclusion ignorés ;
- arrêt immédiat si le serveur refuse l'authentification, et après 3 échecs consécutifs.

Relancez simplement `autopostule envoyer` chaque jour pour continuer là où vous vous êtes arrêté.

## 13. Après l'envoi

```bash
autopostule stats
autopostule exclure rh@societe.fr          # une personne vous demande de ne plus écrire
autopostule exclure societe.fr             # tout un domaine
autopostule exclure 123456789 --raison "déjà postulé via leur site"
```

Répondez rapidement aux recruteurs, et **respectez toute demande de désinscription** (cf. [LEGAL.md](LEGAL.md)).

## 14. Tout automatiser

```bash
autopostule auto -m administrateur_systeme -r hauts-de-france -t CDI   # offres + spontanées
autopostule auto --mode offres -m devops -d 92 -j 3                    # offres récentes uniquement
autopostule auto --mode spontanees -m technicien -r normandie
autopostule auto -m devops -d 92 --ia --approuver-tout   # sans relecture : à vos risques
```

Pour lancer l'envoi chaque matin (Linux/macOS, `crontab -e`) :

```
0 8 * * 1-5 cd /chemin/vers/projet && .venv/bin/autopostule offres rechercher -j 1 && .venv/bin/autopostule offres preparer >> donnees/offres.log 2>&1
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
| `France Travail ignoré : ... absents`            | ajoutez les identifiants dans `.env` (section 7.1)               |
| `401` / `invalid_client` France Travail          | vérifiez l'abonnement de votre application à « Offres d'emploi v2 » |
| `ce site interdit la lecture automatique`        | copiez le texte de l'offre et utilisez `offres ajouter --fichier` |
| `CV structuré absent`                            | `autopostule cv-structure`, puis complétez `cv/cv.yaml`          |
| les e-mails arrivent en spam                     | baissez `max_par_jour`, personnalisez la lettre, évitez les liens |
