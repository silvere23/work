# Architecture

## Vue d'ensemble

```
autopostule/
├── cli.py            # commandes (argparse) et enchaînement des étapes
├── candidature.py    # préparation d'une candidature (offre ou spontanée) : e-mail, CV adapté, lettre
├── offres.py         # sources d'offres (France Travail, Adzuna, URL, texte), filtres, mots-clés, métier
├── cv_adapte.py      # CV structuré (cv.yaml) -> CV PDF adapté à une offre
├── ia.py             # appel à Claude (lettres, accroche du CV)
├── pdfutil.py        # mise en page PDF commune (polices Unicode, translittération)
├── interface/        # interface web locale (Flask) : `autopostule interface`
│   ├── __init__.py   # routes, lecture/écriture de config.yaml et .env, jeton anti-CSRF
│   ├── taches.py     # opérations longues en arrière-plan, journal capturé par fil d'exécution
│   ├── templates/    # pages HTML (Jinja2)
│   └── static/       # feuille de style (thème clair / sombre)
├── config.py         # lecture de config.yaml + .env, valeurs par défaut
├── referentiel.py    # régions, départements, métiers, codes NAF, tranches d'effectif
├── cv.py             # extraction du texte du CV, coordonnées, compétences, adéquation métier
├── entreprises.py    # client de l'API « Recherche d'entreprises » (SIRENE)
├── web.py            # client HTTP poli : robots.txt, délai par hôte, timeouts, taille max
├── sites.py          # découverte et vérification du site, exploration des pages utiles
├── emails.py         # extraction (mailto, texte, obfuscations, Cloudflare) et classement des adresses
├── lettre.py         # rédaction (modèle Jinja2 ou Claude), accords, export PDF
├── envoi.py          # construction MIME, SMTP, plafonds, délais, mode test
├── stockage.py       # base SQLite (entreprises, e-mails, candidatures, exclusions)
└── templates/
    ├── config.exemple.yaml
    ├── cv.exemple.yaml
    ├── lettre.txt.j2
    └── mail.txt.j2
```

## Flux de données

Offres :

```
offres rechercher ──► offres (statut = nouvelle)            [France Travail, Adzuna]
offres ajouter    ──► offres (statut = nouvelle)            [URL JobPosting / texte]
offres preparer   ──► e-mail de l'offre, ou SIRENE (par_nom) + scan du site → adresse RH
                  ──► donnees/offres/<id>/ : CV adapté, lettre, message, offre.txt
                  ──► candidature (brouillon, offre_id, cv_pdf) + offre = preparee
                      ou offre = a_postuler_sur_site
envoyer           ──► candidature = envoyee, offre = postulee
```

Candidatures spontanées :

```
rechercher ──► entreprises (statut_scan = a_scanner)
scanner    ──► entreprises.site + emails ; statut_scan = scanne | sans_site | sans_email
generer    ──► candidatures (statut = brouillon) + donnees/lettres/*.pdf
approuver  ──► candidatures.statut = approuvee
envoyer    ──► candidatures.statut = envoyee | echec | ignoree
```

Chaque étape est **reprenable** : elle ne traite que ce qui n'a pas encore été traité. Vous pouvez donc
lancer `rechercher` plusieurs fois avec d'autres régions, `scanner -n 20` par lots, etc.

## Base de données (`donnees/autopostule.db`)

| Table          | Clé                 | Contenu principal                                                     |
|----------------|---------------------|-----------------------------------------------------------------------|
| `entreprises`  | `siren`             | nom, NAF, adresse, ville, département, région, effectif, métier visé, site, confiance du site, statut du scan |
| `emails`       | `(siren, email)`    | type (`rh`, `generique`, `nominatif`, `autre`), score, page source    |
| `candidatures` | `id`                | e-mail, objet, corps du message, lettre, chemin du PDF, moteur, statut, erreur, dates, Message-ID |
| `exclusions`   | `valeur`            | e-mail, domaine ou SIREN à ne jamais contacter                        |
| `offres`       | `id`                | source, intitulé, entreprise, description, URL, e-mail, lieu, contrat, date, salaire, compétences, référence, métier, clé de doublon, SIREN, statut, dossier |

`candidatures` porte aussi `offre_id` (vide pour une candidature spontanée) et `cv_pdf` (CV adapté joint).
Les colonnes ajoutées en v0.2 sont créées automatiquement sur une base existante (`Base._migrer`).

La base s'ouvre avec n'importe quel outil SQLite (DB Browser for SQLite, `sqlite3`…) pour des exports :

```bash
sqlite3 -header -csv donnees/autopostule.db \
  "SELECT e.nom, e.ville, c.email, c.statut, c.date_envoi FROM candidatures c JOIN entreprises e USING (siren)" \
  > suivi.csv
```

## Recherche d'entreprises

`entreprises.ClientRechercheEntreprises` appelle `https://recherche-entreprises.api.gouv.fr/search` avec :
`activite_principale` (codes NAF du métier), `region` ou `departement`, `tranche_effectif_salarie`,
`etat_administratif=A`. Pagination de 25 résultats, pause entre les pages, nouvelle tentative avec attente
exponentielle sur HTTP 429. Filtres locaux : nature juridique (exclut entrepreneurs individuels,
personnes publiques, associations) et ville.

## Découverte du site et des adresses

1. `sites.slugs_candidats` dérive des noms de domaine plausibles de la raison sociale (sans forme juridique) :
   `ACME INFRA SERVICES SAS` → `acmeinfraservices`, `acme-infra-services`, `acme`, `acmeinfra`, `ais`.
2. `Prospecteur.trouver_site` essaie `https://www.<slug><tld>/` puis `https://<slug><tld>/`, et **vérifie**
   la page (`verifier_site`) : SIREN présent (page d'accueil ou mentions légales) → confiance `siren` ;
   tous les mots du nom dans le titre / l'en-tête → confiance `nom`. Sinon le domaine est rejeté.
3. `Prospecteur.explorer` visite la page d'accueil, les liens internes pertinents (recrutement en premier)
   puis des chemins courants (`/contact`, `/recrutement`, `/nous-rejoindre`…) ; arrêt dès qu'une adresse RH
   est trouvée sur une page de recrutement, ou au bout de `pages_max_par_site`.
4. `emails.extraire_adresses` lit les liens `mailto:`, le texte, les formes obfusquées (`rh [at] acme [dot] fr`)
   et la protection Cloudflare (`data-cfemail`).
5. `emails.classer` rejette les adresses techniques ou hors sujet et celles d'un autre domaine (agence web,
   partenaires), puis attribue type et score.
6. Optionnel : `sites.mx_valide` vérifie l'enregistrement MX du domaine.

`web.Navigateur` garantit le respect de `robots.txt`, un délai minimal par hôte, un timeout et une taille
maximale de page (2 Mo), et n'accepte que du HTML/texte.

## Offres d'emploi

- `SourceFranceTravail` : jeton OAuth2 (`client_credentials`, portée `api_offresdemploiv2 o2dsoffre`), puis
  `GET /offres/search` avec `motsCles`, `region` ou `departement`, `typeContrat` (CDI, CDD, MIS, LIB),
  `publieeDepuis` (1, 3, 7, 14 ou 31), `sort=1`, pagination par `range` de 150.
- `SourceAdzuna` : `GET /v1/api/jobs/fr/search/{page}` avec `what`, `where`, `max_days_old`, `sort_by=date`,
  `permanent=1` / `contract=1`.
- `offre_depuis_url` : respecte `robots.txt`, lit le bloc schema.org `JobPosting` (JSON-LD) ou, à défaut, le
  titre et le texte de la page ; `offre_depuis_texte` pour un copier-coller.
- `collecter` : une requête par métier (`Metier.recherches`) et par zone, puis filtres `est_pertinente`
  (intitulé ou au moins 3 compétences du métier), `contrat_accepte`, ville, et dédoublonnage (`id` +
  `cle_doublon` = intitulé nettoyé + entreprise + ville).
- `mots_cles` : compétences du référentiel et du CV citées par l'offre, classées par fréquence (bonus si
  présentes dans l'intitulé). Elles pilotent le CV adapté et la lettre.

## CV adapté

`cv_adapte.adapter` copie le CV structuré puis : titre = intitulé visé ; compétences triées (demandées
d'abord, dans l'ordre d'importance de l'offre) et catégories triées par nombre de compétences demandées ;
missions de chaque expérience triées par nombre de mots-clés (ordre des expériences inchangé) ; ligne
« Atouts pour ce poste » ou accroche réécrite par Claude (`accroche_ia`, consigne de ne rien inventer).
`manquantes` liste les compétences demandées absentes du CV. `ecrire_pdf` met en page (fpdf2, gras
markdown pour les compétences demandées).

## Rédaction

`lettre.GenerateurLettres.paragraphes` assemble : accroche (variante du métier, ou réponse à l'offre),
parcours (expérience, **réalisations tirées du CV structuré** les plus proches de l'offre, compétences
demandées par l'offre et présentes dans le CV, à défaut compétences du métier), paragraphe entreprise (secteur NAF × taille × proximité),
paragraphe personnel, conclusion (disponibilité, type de contrat). Le choix des variantes dépend d'un hachage `SIREN + métier` : stable pour
une entreprise, varié entre entreprises. `accorder` résout la syntaxe `[masculin|féminin|inclusif]`.

En mode IA, `corps_ia` envoie à Claude (SDK `anthropic`, `client.beta.messages.create`) le CV, le profil,
l'entreprise et le brouillon, avec réflexion adaptative, effort `medium` et repli serveur
(`fallbacks="default"`) pour les modèles qui le prennent en charge. Toute erreur ou tout refus du modèle
déclenche un repli sur le modèle Jinja2.

`ecrire_pdf` utilise fpdf2 avec une police Unicode du système (DejaVu, Arial) ou, à défaut, Helvetica avec
translittération Latin-1.

## Envoi

`envoi.envoyer_candidatures` sélectionne les candidatures `approuvee` (et `brouillon` si la validation
manuelle est désactivée), applique le plafond du jour, la liste d'exclusion et le délai de recontact, puis
envoie via `Expediteur` (SMTP STARTTLS/SSL, ou fichiers `.eml` en mode test). Erreur d'authentification →
arrêt immédiat ; 3 erreurs consécutives → arrêt.

## Étendre l'outil

| Besoin                       | Où intervenir                                                          |
|------------------------------|------------------------------------------------------------------------|
| nouveau métier               | `referentiel.METIERS` (+ alias dans `ALIAS_METIERS`)                    |
| nouvelles compétences        | `Metier.competences` (elles sont aussi détectées dans le CV)           |
| autre secteur d'activité     | `recherche.naf_supplementaires` ou `Metier.naf` ; libellé dans `SECTEURS_NAF` |
| autre source d'entreprises   | produire des dicts au format de `entreprises.convertir` puis `Base.ajouter_entreprise` |
| nouvelle source d'offres     | classe avec `nom` et `rechercher(requete, zones, contrats, jours, limite)` produisant des `Offre`, branchée dans `cli._sources` |
| autre style de lettre        | `lettre.dossier_modeles` (modèles Jinja2 personnels)                    |

## Interface graphique

`interface.creer_app` construit une application Flask qui réutilise les fonctions de la ligne de commande
(`rechercher`, `scanner`, `generer`, `rechercher_offres`, `preparer_offres`, `envoyer_candidatures`).

- **Sécurité** : écoute sur 127.0.0.1 uniquement ; jeton secret aléatoire exigé sur chaque POST (un site
  malveillant ouvert dans le navigateur ne peut pas déclencher d'envoi) ; `/fichier` ne sert que des fichiers
  situés dans le dossier de travail ; les secrets ne sont jamais réaffichés.
- **Tâches de fond** (`taches.Gestionnaire`) : une opération à la fois, exécutée dans un fil dédié ;
  `sys.stdout` est remplacé par un aiguilleur qui envoie les `print` de ce fil dans le journal de la tâche
  (`/taches/<id>.json`, interrogé chaque seconde par la page).
- **Réglages** : le formulaire réécrit `config.yaml` (les commentaires du modèle disparaissent) et met à jour
  les clés de `.env` en conservant les autres lignes ; les nouveaux secrets sont actifs immédiatement.
- **Dossier de travail** mémorisé dans `~/.autopostule.json`.

## Tests

`tests/test_unitaires.py` couvre le référentiel, l'analyse du CV, l'extraction et le classement des adresses,
la conversion des résultats SIRENE, la vérification des sites, les accords et la génération des lettres et PDF.
`tests/test_offres.py` couvre les contrats, la conversion des offres (France Travail, Adzuna, JobPosting),
les mots-clés, le CV adapté, les lettres sur offre et la migration de la base.
`tests/test_offres_integration.py` déroule le parcours « offres » complet via la CLI contre de fausses API
France Travail, Adzuna et SIRENE et un faux SMTP (paramètres envoyés, filtres, doublons, adresse RH, dossier
à déposer, CV adapté joint, statuts).
`tests/test_interface.py` parcourt l'interface avec le client de test Flask : choix du dossier, profil, import
du CV, secrets, CV structuré et aperçu, ajout d'une offre, préparation en tâche de fond, approbation, essai et
envoi (faux SMTP), jeton obligatoire, accès aux fichiers limité au dossier, blocage des valeurs d'exemple.
`tests/test_integration.py` déroule le pipeline complet contre un faux site web et une fausse API locale
(robots.txt, liens externes ignorés), un faux SMTP (plafond, exclusions, pas de doublon) et un faux serveur
Claude (forme exacte de la requête).
