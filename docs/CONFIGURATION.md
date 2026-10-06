# Référence de configuration

`config.yaml` est fusionné avec les valeurs par défaut (`autopostule/templates/config.exemple.yaml`) : vous
pouvez n'indiquer que ce que vous changez. Les chemins relatifs sont résolus par rapport au dossier de
`config.yaml`. Un autre fichier peut être utilisé avec `autopostule -c autre.yaml <commande>`.

## `profil`

| Clé                 | Type    | Exemple                         | Usage                                        |
|---------------------|---------|---------------------------------|----------------------------------------------|
| `prenom`, `nom`     | texte   | `Jean`, `Dupont`                | en-tête, objet, signature, nom des fichiers (**obligatoire**) |
| `genre`             | `M`/`F`/vide | `F`                        | accords grammaticaux et intitulé du poste    |
| `email`             | texte   | `jean@mail.fr`                  | en-tête, signature, `Reply-To` (**obligatoire**) |
| `telephone`         | texte   | `06 12 34 56 78`                | en-tête, signature (**obligatoire**)         |
| `adresse`, `code_postal`, `ville` | texte | `59000`, `Lille`     | en-tête ; proximité avec l'entreprise        |
| `linkedin`, `github`, `portfolio` | URL |                         | signature                                    |
| `titre`             | texte   | `Administrateur systèmes`       | « en tant que … »                            |
| `annees_experience` | entier  | `3`                             | 0 = formulation « jeune diplômé(e) »          |
| `type_contrat`      | texte   | `CDI`, `alternance`             | objet et message                              |
| `disponibilite`     | texte   | `immédiatement`, `à partir de janvier` | conclusion                           |
| `mobilite`          | texte   | `Hauts-de-France`               | transmis à l'IA                               |

## `cv`

| Clé       | Défaut            | Description                                       |
|-----------|-------------------|---------------------------------------------------|
| `fichier` | `cv/mon_cv.pdf`   | PDF, DOCX, TXT ou MD ; analysé et joint aux mails |

## `recherche`

| Clé                    | Défaut                       | Description                                    |
|------------------------|------------------------------|------------------------------------------------|
| `metiers`              | `[administrateur_systeme]`   | `administrateur_reseau`, `administrateur_systeme`, `technicien_informatique`, `devops`, `cybersecurite`, `developpeur` |
| `regions`              | `[ile-de-france]`            | clés de `autopostule regions` ; alias `idf`, `hdf`, `paca`, `aura`… |
| `departements`         | `[]`                         | ex. `["59", "62"]` ; prioritaire sur `regions` |
| `villes`               | `[]`                         | filtre sur la commune du siège                 |
| `effectif_min`         | `10`                         | 0 = toutes tailles                             |
| `naf_supplementaires`  | `[]`                         | codes NAF ajoutés à ceux du métier             |
| `limite`               | `200`                        | entreprises max par métier et par recherche    |

Codes NAF utilisés par défaut (voir `autopostule metiers`) :

| Code    | Activité                                                     |
|---------|--------------------------------------------------------------|
| 62.01Z  | Programmation informatique                                   |
| 62.02A  | Conseil en systèmes et logiciels informatiques (ESN)         |
| 62.02B  | Tierce maintenance de systèmes et d'applications             |
| 62.03Z  | Gestion d'installations informatiques (infogérance)          |
| 62.09Z  | Autres activités informatiques                               |
| 63.11Z  | Traitement de données, hébergement                           |
| 58.29A/B/C | Édition de logiciels                                      |
| 61.10Z / 61.20Z / 61.90Z | Télécommunications                          |
| 95.11Z  | Réparation d'ordinateurs                                     |
| 46.51Z  | Commerce de gros de matériel informatique                    |
| 80.20Z  | Activités liées aux systèmes de sécurité                     |

## `scan`

| Clé                         | Défaut                         | Description                                 |
|-----------------------------|--------------------------------|---------------------------------------------|
| `pages_max_par_site`        | `8`                            | pages visitées au maximum par site          |
| `delai_entre_requetes`      | `1.5`                          | secondes entre deux requêtes sur un site    |
| `timeout`                   | `15`                           | délai maximum d'une requête (s)             |
| `inclure_emails_nominatifs` | `false`                        | autorise `prenom.nom@` (voir LEGAL.md)      |
| `verifier_mx`               | `true`                         | écarte les domaines sans serveur de messagerie |
| `tlds`                      | `[.fr, .com, .io, .eu, .net]`  | extensions essayées pour deviner le site    |

## `lettre`

| Clé                | Défaut             | Description                                                  |
|--------------------|--------------------|--------------------------------------------------------------|
| `moteur`           | `modele`           | `modele` (Jinja2, hors ligne) ou `ia` (Claude)               |
| `modele_ia`        | `claude-opus-5-5`  | modèle Claude utilisé en mode IA                             |
| `joindre_pdf`      | `true`             | `true` : message court + lettre PDF ; `false` : lettre dans le corps |
| `paragraphe_perso` | vide               | paragraphe ajouté avant la conclusion de chaque lettre       |
| `dossier_modeles`  | vide               | dossier contenant vos `lettre.txt.j2` / `mail.txt.j2`        |

## `envoi`

| Clé                     | Défaut            | Description                                              |
|-------------------------|-------------------|----------------------------------------------------------|
| `smtp_hote`             | `smtp.gmail.com`  | serveur SMTP                                             |
| `smtp_port`             | `587`             | 587 (STARTTLS) ou 465 (SSL)                              |
| `securite`              | `starttls`        | `starttls` ou `ssl`                                      |
| `smtp_utilisateur`      | vide              | identifiant SMTP (souvent votre adresse)                 |
| `expediteur`            | vide              | adresse d'expédition si différente de l'identifiant      |
| `max_par_jour`          | `40`              | plafond d'envois sur une journée                          |
| `delai_min_s` / `delai_max_s` | `60` / `180` | pause aléatoire entre deux envois                       |
| `validation_manuelle`   | `true`            | n'envoie que les candidatures approuvées                 |
| `delai_recontact_jours` | `120`             | délai avant de pouvoir recontacter une entreprise        |
| `copie_cachee_a_moi`    | `false`           | vous met en copie cachée de chaque envoi                 |

## `donnees`

| Clé       | Défaut     | Description                                                       |
|-----------|------------|-------------------------------------------------------------------|
| `dossier` | `donnees`  | base `autopostule.db`, `lettres/`, `pieces/`, `envois_test/`      |

## Variables d'environnement (`.env`)

| Variable                    | Description                                         |
|-----------------------------|-----------------------------------------------------|
| `AUTOPOSTULE_SMTP_PASSWORD` | mot de passe SMTP (mot de passe d'application Gmail) |
| `ANTHROPIC_API_KEY`         | clé API Claude (mode IA uniquement)                 |
