# Cadre légal et bonnes pratiques

> Ce document donne des repères, il ne constitue pas un avis juridique.

Envoyer des candidatures spontanées est une démarche normale et légitime. Les règles ci-dessous visent à
rester dans le cadre du **RGPD**, des recommandations de la **CNIL** et des conditions d'utilisation des
services utilisés, et à préserver votre réputation auprès des recruteurs et des filtres anti-spam.

## Collecte des adresses

- **Sources** : uniquement des données publiques — base SIRENE (données ouvertes de l'INSEE, via l'API
  officielle) et pages publiques des sites des entreprises.
- **Adresses génériques d'abord** : `recrutement@`, `rh@`, `jobs@`, `contact@`… sont des adresses de
  fonction publiées pour être contactées ; c'est le choix par défaut.
- **Adresses nominatives** (`prenom.nom@`) : ce sont des données personnelles au sens du RGPD. La CNIL admet
  la prospection B2B par e-mail sans consentement préalable si le message est **en rapport avec la fonction**
  de la personne (une candidature adressée à un ou une responsable RH l'est) et si la personne peut
  **s'opposer facilement**. Elles restent désactivées par défaut (`inclure_emails_nominatifs: false`) ;
  activez-les en connaissance de cause.
- **Respect des sites** : `robots.txt` est respecté, les requêtes sont espacées, le nombre de pages par site
  est limité.
- **Offres d'emploi** : récupérées par les **API officielles** de France Travail et d'Adzuna, prévues pour
  cet usage, ou ajoutées par vous (lien ou copier-coller).
- **LinkedIn, Indeed, Welcome to the Jungle…** : leurs conditions d'utilisation interdisent l'extraction
  automatisée et l'utilisation de robots pour postuler. Ces plateformes détectent ces robots et suspendent
  les comptes concernés (LinkedIn a poursuivi en justice des sociétés d'extraction de données). L'outil ne
  les interroge donc pas automatiquement et ne remplit pas leurs formulaires : ajoutez leurs offres avec
  `offres ajouter --fichier` (texte copié) et déposez la candidature vous-même avec le dossier préparé.
  Beaucoup de ces offres sont aussi diffusées sur France Travail ou référencées par Adzuna.

## Conservation des données

Les données collectées restent **sur votre ordinateur** (`donnees/autopostule.db`). Supprimez-les quand votre
recherche est terminée (supprimez simplement le dossier `donnees/`). Ne les revendez pas et ne les partagez
pas.

## Envoi

- **Identifiez-vous clairement** : vos nom, téléphone et adresse figurent dans chaque message.
- **Droit d'opposition** : chaque e-mail indique comment ne plus être contacté. Si quelqu'un vous le
  demande, exécutez `autopostule exclure <adresse ou domaine>` : l'outil ne le recontactera jamais.
- **Une candidature par offre**, et une seule candidature spontanée par entreprise, sans relance avant
  120 jours (paramétrable).
- **CV et lettres sincères** : l'outil réorganise et met en avant votre parcours mais n'ajoute aucune
  compétence ni expérience. Relisez ce qui part en votre nom.
- **Volume raisonnable** : 20 à 40 envois par jour. Au-delà, Gmail/Outlook peuvent bloquer votre compte, et
  vos messages risquent d'arriver en spam chez tous vos destinataires.
- **Qualité plutôt que quantité** : ciblez les bons métiers et les bonnes zones, relisez les lettres
  (validation manuelle activée par défaut). Une lettre pertinente obtient plus de réponses que dix lettres
  génériques.

## Clé API et mots de passe

`.env` contient des secrets : ne le versionnez pas (il est dans `.gitignore`), ne l'envoyez à personne.
Utilisez un **mot de passe d'application** dédié, révocable à tout moment, plutôt que votre mot de passe
principal.
