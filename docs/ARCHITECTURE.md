# Architecture

## Vue d'ensemble

```
autopostule/
├── cli.py            # commandes (argparse) et enchaînement des étapes
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
    ├── lettre.txt.j2
    └── mail.txt.j2
```

## Flux de données

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

## Rédaction

`lettre.GenerateurLettres.paragraphes` assemble : accroche (variante du métier), parcours (expérience,
missions, compétences du CV filtrées par métier), paragraphe entreprise (secteur NAF × taille × proximité),
paragraphe personnel, conclusion. Le choix des variantes dépend d'un hachage `SIREN + métier` : stable pour
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
| offres d'emploi France Travail | API officielle « Offres d'emploi » (inscription gratuite sur francetravail.io) : piste d'évolution |
| autre style de lettre        | `lettre.dossier_modeles` (modèles Jinja2 personnels)                    |

## Tests

`tests/test_unitaires.py` couvre le référentiel, l'analyse du CV, l'extraction et le classement des adresses,
la conversion des résultats SIRENE, la vérification des sites, les accords et la génération des lettres et PDF.
`tests/test_integration.py` déroule le pipeline complet contre un faux site web et une fausse API locale
(robots.txt, liens externes ignorés), un faux SMTP (plafond, exclusions, pas de doublon) et un faux serveur
Claude (forme exacte de la requête).
