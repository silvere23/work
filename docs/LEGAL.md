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
- **Plateformes exclues** : LinkedIn, Indeed, Welcome to the Jungle, etc. interdisent l'extraction
  automatisée dans leurs conditions d'utilisation ; l'outil ne les visite pas. Postulez-y à la main.

## Conservation des données

Les données collectées restent **sur votre ordinateur** (`donnees/autopostule.db`). Supprimez-les quand votre
recherche est terminée (supprimez simplement le dossier `donnees/`). Ne les revendez pas et ne les partagez
pas.

## Envoi

- **Identifiez-vous clairement** : vos nom, téléphone et adresse figurent dans chaque message.
- **Droit d'opposition** : chaque e-mail indique comment ne plus être contacté. Si quelqu'un vous le
  demande, exécutez `autopostule exclure <adresse ou domaine>` : l'outil ne le recontactera jamais.
- **Une candidature par entreprise**, pas de relance avant 120 jours (paramétrable).
- **Volume raisonnable** : 20 à 40 envois par jour. Au-delà, Gmail/Outlook peuvent bloquer votre compte, et
  vos messages risquent d'arriver en spam chez tous vos destinataires.
- **Qualité plutôt que quantité** : ciblez les bons métiers et les bonnes zones, relisez les lettres
  (validation manuelle activée par défaut). Une lettre pertinente obtient plus de réponses que dix lettres
  génériques.

## Clé API et mots de passe

`.env` contient des secrets : ne le versionnez pas (il est dans `.gitignore`), ne l'envoyez à personne.
Utilisez un **mot de passe d'application** dédié, révocable à tout moment, plutôt que votre mot de passe
principal.
