# Suivi X → Discord #twitter

Tous les jours à **9h00**, un relevé du compte @Bristan_FARRE est posté dans
le salon `#twitter` du serveur Discord *Sellify Apps*.

## Comment ça marche

Aucune clé d'API X (l'accès aux likes par post coûte 200 $/mois). Le script
rejoue les appels du client web x.com avec les **cookies de la session Chrome**,
lus directement dans le profil Chrome et déchiffrés via le trousseau macOS
(`cookies.py`). Les `queryId` GraphQL changent à chaque déploiement de X : ils
sont redécouverts dans le bundle `main.js` **à chaque exécution**, donc une mise
à jour de X ne casse rien.

| Fichier | Rôle |
|---|---|
| `cookies.py` | extrait `auth_token` + `ct0` du profil Chrome |
| `releve.py` | relève, compare à hier, poste sur Discord |
| `config.json` | l'URL du webhook Discord (**secret**, hors dépôt — copier `config.exemple.json`) |
| `fr.sellify.x-suivi.plist` | tâche launchd de 9h (à copier dans `~/Library/LaunchAgents`, chemins à adapter) |
| `historique.jsonl` | un snapshot complet par jour — la mémoire des deltas |
| `journal.log` | sortie de la tâche de 9h |

## Ce qui est posté

**Chaque jour à 9h00**, deux cartes : la **journée UTC complète de la veille**
en tuiles (abonnés, conseils postés, impressions, j'aime, réponses,
interactions, visites de profil, clics, abonnés gagnés, likes donnés) et la
liste des **conversations ouvertes** — les marchands qui ont répondu à un
conseil, avec le lien du fil. **Le lundi**, une troisième carte : le récap des
7 journées closes, en tableau jour par jour, avec les totaux comparés à la
semaine précédente.

On affiche la veille et pas le jour même parce que **les impressions d'un post
mettent 24 à 48 h à se stabiliser** : le chiffre du jour même est toujours
sous-évalué.

Pour voir les cartes sans rien poster :
`python3 releve.py --essai` (ajouter `--semaine` pour forcer le récap).

## Ce qui est relevé

Abonnés, abonnements, total de posts, likes donnés (le quota de 20/jour), et
pour **chaque post et chaque réponse** (timelines paginées jusqu'au bout, 90 j
conservés) : likes, réponses, reposts, citations, signets, vues. Les deltas
sont calculés post par post entre deux relevés, donc l'engagement reçu ne
compte jamais deux fois.

### L'entonnoir (Analytics)

L'onglet Analytics du client web expose, **poste par poste et réponse par
réponse** : impressions, visites de profil, abonnés gagnés, clics sur le lien,
dépliages. C'est l'endpoint `contentPageQuery`. Deux choses à savoir :

- Son `queryId` **n'est pas dans main.js** (module chargé à la demande). Il est
  donc écrit en dur dans `releve.py` (`ANALYTICS_QID`). S'il tombe en 404, le
  relevé continue sans l'entonnoir et l'écrit dans `journal.log` ; pour le
  réparer, ouvrir `x.com/i/account_analytics` → onglet *Content* dans Chrome et
  relire l'URL de la requête `contentPageQuery`.
- La page « Overview » de X est verrouillée sous 50 abonnés, **mais pas cet
  endpoint** : les chiffres sont là avant le seuil.

Ces métriques sont **datées par X**, donc justes dès le premier relevé et
reconstituables dans le passé — contrairement aux compteurs de profil.

**Deux familles de chiffres, à ne pas confondre :**

*Ce qui se déduit du seul relevé du jour* — conseils postés par jour, moyenne
7 j, part des conseils qui ont fait réagir, conversations ouvertes. Ces
chiffres remontent au premier post du compte, même sans historique.

*Ce qui exige un relevé de la veille* — le compteur d'abonnés et le compteur de
likes donnés. X ne publie aucun historique de ces deux compteurs : ils ne
peuvent pas être reconstitués après coup. Si l'écart entre deux relevés est
inférieur à 12 h, ces variations ne sont pas affichées plutôt que d'afficher
un « +0 » qui ne veut rien dire.

Une réponse à soi-même (fil) n'est jamais comptée comme un conseil.

## Commandes

```bash
python3 releve.py --essai   # affiche le message sans le poster ni l'archiver
python3 releve.py           # relève, poste, archive
launchctl list | grep x-suivi
```

## Le seul truc qui peut casser

**Les cookies expirent** (quelques mois, ou si tu te déconnectes de X dans
Chrome). Symptôme : plus rien à 9h et une erreur dans `journal.log`. Correctif :
se reconnecter à x.com dans Chrome, rien d'autre à faire.

## Le piège de la pagination

Les timelines ne contiennent pas que tes posts : elles charrient aussi les
messages des marchands auxquels tu réponds, qui peuvent avoir des mois. Toute
condition d'arrêt fondée sur « le plus ancien tweet vu » s'arrête donc au
premier vieux post d'un tiers — la collecte rendait 26 posts sur 107 sans rien
signaler. On ne filtre que sur `user_id_str == uid`.

Corollaire : le script refuse de poster tant qu'il n'a pas soit **tout** le
compte, soit 90 jours pleins de *tes* posts, et il réessaie trois fois à cinq
minutes d'intervalle avant d'abandonner.

## Supprimer un message déjà posté

Le webhook peut effacer ses propres messages sans aucun jeton supplémentaire :

```bash
curl -X DELETE "$(python3 -c "import json;print(json.load(open('config.json'))['webhook_discord'])")/messages/<id_du_message>"
```

L'identifiant se lit dans le DOM de Discord (`li[id^="chat-messages-"]`) ou en
faisant « Copier le lien du message » (le dernier segment de l'URL). Le menu
contextuel de Discord dans le navigateur ne réagit pas toujours aux clics
automatisés — cette voie est plus fiable.

## La courbe des abonnés

`courbe.py` dessine un PNG (PIL) en double résolution, aux couleurs de Discord,
joint au message — aucun hébergeur externe. Deux pièges rencontrés :

- Discord **n'écho pas** les pièces jointes dans sa réponse (`attachments: []`)
  même quand l'envoi a réussi : ne pas s'y fier pour diagnostiquer, regarder le
  salon. Chaque fichier doit être déclaré dans `attachments` du `payload_json`
  pour qu'un embed puisse le viser avec `attachment://`.
- Un graphique au fond identique à celui de l'embed passe pour une case vide.
  D'où un panneau plus sombre, un trait épais et un remplissage sous la courbe.

La courbe n'apparaît qu'à partir de **deux journées** d'historique : X ne
publie pas le passé du compteur d'abonnés, la série se construit relevé après
relevé (14 jours affichés).
