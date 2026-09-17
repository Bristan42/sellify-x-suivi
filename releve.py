#!/usr/bin/env python3
"""Relevé quotidien du compte X @Bristan_FARRE, posté dans Discord #twitter.

Aucune clé d'API : on rejoue les appels du client web avec les cookies de
session Chrome (voir cookies.py). Les queryId GraphQL changent à chaque
déploiement de X, donc on les redécouvre dans le bundle main.js à chaque run.
"""
import json, os, re, sys, time, urllib.request, urllib.parse, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cookies as ck
import courbe

ICI = os.path.dirname(os.path.abspath(__file__))
COMPTE = "Bristan_FARRE"
HIST = os.path.join(ICI, "historique.jsonl")
CONF = os.path.join(ICI, "config.json")
# L'onglet Analytics du client web. Ce queryId n'est PAS dans main.js (module
# chargé à la demande) : s'il tombe en 404, ouvrir x.com/i/account_analytics
# → onglet Content dans Chrome et relire l'URL de la requête contentPageQuery.
ANALYTICS_QID = "eyqFN-MJHrF7Aq4O5aFBpQ"
METRIQUES = ["Impressions", "Engagements", "Likes", "Replies", "Retweets", "Bookmark",
             "Follows", "ProfileVisits", "DetailExpands", "UrlClicks"]
BEARER = ("AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
          "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def _get(url, headers, timeout=30):
    """X renvoie des 429 quand on enchaîne les pages : on patiente et on réessaie."""
    for essai in range(4):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=timeout).read().decode("utf8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code != 429 or essai == 3:
                raise
            time.sleep(60 * (essai + 1))


class X:
    def __init__(self, forcer_cookies=False):
        c = ck.x_cookies(forcer=forcer_cookies)
        if "auth_token" not in c or "ct0" not in c:
            raise SystemExit("cookies x.com introuvables — ouvre x.com dans Chrome et reconnecte-toi")
        self.h = {
            "authorization": "Bearer " + BEARER, "x-csrf-token": c["ct0"],
            "cookie": "auth_token=%s; ct0=%s" % (c["auth_token"], c["ct0"]),
            "x-twitter-active-user": "yes", "x-twitter-auth-type": "OAuth2Session",
            "referer": "https://x.com/" + COMPTE, "user-agent": UA,
        }
        self.qid, self.feats = self._bundle()

    def _bundle(self):
        """queryId + liste des feature flags, extraits du bundle JS courant."""
        html = _get("https://x.com/" + COMPTE, {"user-agent": UA, "cookie": self.h["cookie"]})
        urls = re.findall(r'https://abs\.twimg\.com/responsive-web/client-web[^"\']+?main[^"\']*?\.js', html)
        if not urls:
            raise SystemExit("bundle main.js introuvable dans la page X")
        js = _get(urls[0], {"user-agent": UA}, timeout=60)
        qid = dict((n, q) for q, n in re.findall(r'queryId:"([\w-]+)",operationName:"(\w+)"', js))
        qid.update((n, q) for n, q in re.findall(r'operationName:"(\w+)",queryId:"([\w-]+)"', js))
        i = js.find('operationName:"UserTweetsAndReplies"')
        f = re.findall(r'featureSwitches:\[([^\]]*)\]', js[max(0, i - 200):i + 3000])
        feats = {k: True for k in re.findall(r'"([^"]+)"', f[0])} if f else {}
        return qid, feats

    def gql(self, op, var):
        u = "https://x.com/i/api/graphql/%s/%s?variables=%s&features=%s" % (
            self.qid[op], op, urllib.parse.quote(json.dumps(var)),
            urllib.parse.quote(json.dumps(self.feats)))
        return json.loads(_get(u, self.h))

    def profil(self):
        r = self.gql("UserByScreenName",
                     {"screen_name": COMPTE, "withSafetyModeUserFields": True})
        return r["data"]["user"]["result"]

    def timeline(self, op, uid, count=40, cursor=None):
        var = {"userId": uid, "count": count, "includePromotedContent": False,
               "withCommunity": False, "withVoice": False, "withV2Timeline": True}
        if cursor:
            var["cursor"] = cursor
        return self.gql(op, var)


def analytics(x, depuis, jusqu):
    """Les vraies métriques X (impressions, visites de profil, abonnés gagnés,
    clics sur le lien), post par post et réponse par réponse."""
    var = {"from_time": depuis.strftime("%Y-%m-%dT00:00:00.000Z"),
           "to_time": jusqu.strftime("%Y-%m-%dT23:59:59.999Z"),
           "max_results": 1000, "query_page_size": 100, "requested_metrics": METRIQUES}
    u = "https://x.com/i/api/graphql/%s/contentPageQuery?variables=%s" % (
        ANALYTICS_QID, urllib.parse.quote(json.dumps(var)))
    r = json.loads(_get(u, x.h, timeout=60))
    out = {}
    for t in r["data"]["viewer_v2"]["user_results"]["result"]["tweets_results"]:
        res = t.get("result") or {}
        out[res.get("rest_id")] = {m["metric_type"]: (m.get("metric_value") or 0)
                                   for m in (res.get("organic_metrics_total") or [])}
    return out


def _walk(o, out):
    """Ramasse tous les tweets d'une réponse de timeline, quelle que soit sa forme."""
    if isinstance(o, dict):
        if o.get("__typename") == "Tweet" and "legacy" in o:
            out[o.get("rest_id")] = o
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def _curseur(o):
    """Le curseur de bas de page d'une timeline, pour aller chercher la suite."""
    if isinstance(o, dict):
        if str(o.get("entryId", "")).startswith("cursor-bottom"):
            c = o.get("content") or o.get("item") or {}
            v = c.get("value") or (c.get("content") or {}).get("value")
            if v:
                return v
        for v in o.values():
            r = _curseur(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _curseur(v)
            if r:
                return r


def posts(x, uid):
    """Tout l'historique : X pagine, donc on déroule jusqu'au bout."""
    tous = {}
    for op in ("UserTweets", "UserRepliesTimeline"):
        if op not in x.qid:
            continue
        cur = None
        for _ in range(20):
            try:
                r = x.timeline(op, uid, count=100, cursor=cur)
            except Exception as e:
                # un relevé amputé vaut moins que pas de relevé : on renonce
                raise SystemExit("%s a échoué (%s) — rien n'est posté ni archivé" % (op, e))
            avant = len(tous)
            _walk(r, tous)
            cur = _curseur(r)
            if len(tous) == avant or not cur:
                break
            # Inutile de remonter plus loin que la fenêtre qu'on conserve — mais
            # on ne regarde QUE nos propres posts : les timelines charrient aussi
            # les messages des marchands, qui peuvent avoir des mois.
            miens = [t.get("legacy", {}).get("created_at") for t in tous.values()
                     if t.get("legacy", {}).get("user_id_str") == uid]
            limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=95)
            if miens and min(_dtx(v) for v in miens if v) < limite:
                break
            time.sleep(2)
    out = []
    for tid, t in tous.items():
        lg = t.get("legacy", {})
        if lg.get("user_id_str") != uid:      # les posts des autres dans les fils
            continue
        out.append({
            "id": tid,
            "date": lg.get("created_at"),
            "texte": (t.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {}).get("text")
                      or lg.get("full_text", ""))[:280],
            "likes": lg.get("favorite_count", 0),
            "reponses": lg.get("reply_count", 0),
            "reposts": lg.get("retweet_count", 0),
            "citations": lg.get("quote_count", 0),
            "signets": lg.get("bookmark_count", 0),
            "vues": int((t.get("views") or {}).get("count") or 0),
            "reponse_a": lg.get("in_reply_to_screen_name"),
        })
    return out


def releve(forcer_cookies=False):
    x = X(forcer_cookies)
    p = x.profil()
    lg = p.get("legacy", {}) or {}
    core = p.get("core", {}) or {}
    rc = (p.get("relationship_counts") or {})
    tc = (p.get("tweet_counts") or {})
    liste = posts(x, p["rest_id"])
    vieux = min((_dtx(q["date"]) for q in liste if q["date"]), default=None)
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    total = (p.get("tweet_counts") or {}).get("tweets", (p.get("legacy") or {}).get("statuses_count", 0))
    # on n'a le droit de s'arrêter que si on a tout le compte, ou 90 jours pleins.
    # « Tout le compte » = on est remonté jusqu'au jour de sa création : X compte
    # aussi les posts supprimés dans son total, qui ne sera donc jamais atteint.
    cree = core.get("created_at") or lg.get("created_at")
    debut = _dtx(cree) + dt.timedelta(days=1) if cree else None
    depuis_creation = vieux is not None and debut is not None and vieux <= debut
    if len(liste) < total and not depuis_creation and (vieux is None or vieux > limite):
        raise SystemExit("collecte incomplète (%d posts sur %d, plus ancien %s) — "
                         "rien n'est posté ni archivé"
                         % (len(liste), total, vieux.date() if vieux else "?"))
    snap = {
        "horodatage": dt.datetime.now().isoformat(timespec="seconds"),
        "abonnes": rc.get("followers", lg.get("followers_count", 0)),
        "abonnements": rc.get("following", lg.get("friends_count", 0)),
        "posts_total": tc.get("tweets", lg.get("statuses_count", 0)),
        "likes_donnes": (p.get("action_counts") or {}).get("favorites_count",
                        lg.get("favourites_count", 0)),
        "medias": (p.get("media_counts") or {}).get("media_count", lg.get("media_count", 0)),
        "nom": core.get("name") or lg.get("name"),
        # on garde 90 jours de posts : au-delà, un snapshot par jour ferait
        # grossir l'historique pour rien (les vieux posts ne bougent plus)
        "posts": [q for q in _avec_analytics(x, liste)
                  if q["date"] and _dtx(q["date"]) > dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)],
    }
    return snap


def _avec_analytics(x, liste):
    """Greffe les métriques Analytics sur les posts. En cas d'échec (queryId
    périmé), le relevé continue sans elles plutôt que de ne rien envoyer."""
    try:
        m = analytics(x, dt.date.today() - dt.timedelta(days=90), dt.date.today())
    except Exception as e:
        raise SystemExit("Analytics indisponible (%s) — rien n'est posté ni archivé" % e)
    for q in liste:
        a = m.get(q["id"], {})
        q["impressions"] = a.get("Impressions", 0)
        q["visites_profil"] = a.get("ProfileVisits", 0)
        q["abonnes_gagnes"] = a.get("Follows", 0)
        q["clics_lien"] = a.get("UrlClicks", 0)
        q["deplies"] = a.get("DetailExpands", 0)
        q["engagements"] = a.get("Engagements", 0)
        q["likes_recus"] = a.get("Likes", 0)
        q["reponses_recues"] = a.get("Replies", 0)
        q["reposts_recus"] = a.get("Retweets", 0)
        q["signets_recus"] = a.get("Bookmark", 0)
    return liste


def charger_hist():
    if not os.path.exists(HIST):
        return []
    return [json.loads(l) for l in open(HIST) if l.strip()]


def fr(n):
    return format(int(n), ",d").replace(",", " ")


def signe(n):
    return ("+" if n >= 0 else "−") + fr(abs(n))


def _dtx(s):
    return dt.datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")


MOIS = ["janv.", "févr.", "mars", "avril", "mai", "juin", "juil.", "août",
        "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
CUMULS = ("impressions", "likes_recus", "reponses_recues", "reposts_recus",
          "visites_profil", "clics_lien", "abonnes_gagnes", "deplies", "engagements")


def _jour_fr(d):
    return "%d %s %d" % (d.day, MOIS[d.month - 1], d.year)


def par_jour(snap):
    """Les posts du relevé, regroupés par journée UTC, avec leurs cumuls."""
    out = {}
    for p in snap["posts"]:
        if not p["date"]:
            continue
        j = _dtx(p["date"]).date()
        c = out.setdefault(j, {"posts": 0, "conseils": 0})
        c["posts"] += 1
        if p["reponse_a"] and p["reponse_a"] != COMPTE:
            c["conseils"] += 1
        for k in CUMULS:
            c[k] = c.get(k, 0) + p.get(k, 0)
    return out


def _tuile(nom, valeur, detail=None, inline=True):
    return {"name": nom, "value": "**%s**%s" % (valeur, "\n" + detail if detail else ""),
            "inline": inline}


def _vs(v, ref, unite="vs la veille"):
    if ref is None:
        return None
    e = v - ref
    if e == 0:
        return "stable " + unite
    return "%s%s %s" % ("+" if e > 0 else "−", fr(abs(e)), unite)


def carte_jour(snap, hist):
    """La journée UTC complète (hier), en tuiles — les chiffres du jour même
    ne sont pas mûrs : les impressions d'un post mettent 24 à 48 h à monter."""
    jours = par_jour(snap)
    j = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date()
    a = jours.get(j, {})
    b = jours.get(j - dt.timedelta(days=1))

    def v(cle):
        return a.get(cle, 0)

    def ref(cle):
        return b.get(cle, 0) if b else None

    # abonnés et likes donnés : seuls compteurs sans historique chez X
    prec = hist[-1] if hist else None
    now = dt.datetime.fromisoformat(snap["horodatage"])
    ecart = (now - dt.datetime.fromisoformat(prec["horodatage"])).total_seconds() / 3600 if prec else None
    comp = ecart is not None and ecart >= 12
    dab = _vs(snap["abonnes"], prec["abonnes"]) if comp else "référence de départ"
    dlk = _vs(snap["likes_donnes"], prec["likes_donnes"]) if comp else "référence de départ"

    imp, cons = v("impressions"), v("conseils")
    champs = [
        _tuile("Abonnés", fr(snap["abonnes"]), dab),
        _tuile("Conseils postés", fr(cons), _vs(cons, ref("conseils"))),
        _tuile("Impressions", fr(imp),
               "%s\n%.1f par conseil" % (_vs(imp, ref("impressions")) or "", imp / float(cons) if cons else 0)),
        _tuile("J'aime reçus", fr(v("likes_recus")), _vs(v("likes_recus"), ref("likes_recus"))),
        _tuile("Réponses reçues", fr(v("reponses_recues")), _vs(v("reponses_recues"), ref("reponses_recues"))),
        _tuile("Interactions", fr(v("engagements")), _vs(v("engagements"), ref("engagements"))),
        _tuile("Visites de profil", fr(v("visites_profil")), _vs(v("visites_profil"), ref("visites_profil"))),
        _tuile("Clics sur le lien", fr(v("clics_lien")), _vs(v("clics_lien"), ref("clics_lien"))),
        _tuile("Abonnés gagnés", fr(v("abonnes_gagnes")),
               "attribués aux posts du jour\n%s" % (_vs(v("abonnes_gagnes"), ref("abonnes_gagnes")) or "")),
        _tuile("Likes donnés", fr(snap["likes_donnes"]), "%s · objectif 20/jour" % dlk),
        _tuile("Abonnements", fr(snap["abonnements"])),
        _tuile("Posts au total", fr(snap["posts_total"])),
    ]
    return {"title": "X — @%s · %s" % (COMPTE, _jour_fr(j)), "color": 0x1D9BF0, "fields": champs,
            "footer": {"text": "Journée UTC complète · x-suivi"}}


def carte_semaine(snap):
    """Sept journées UTC complètes, en tableau, plus les totaux."""
    jours = par_jour(snap)
    fin = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date()
    serie = [(fin - dt.timedelta(days=i)) for i in range(6, -1, -1)]
    prec = [(fin - dt.timedelta(days=i)) for i in range(13, 6, -1)]

    def tot(lot, cle):
        return sum(jours.get(j, {}).get(cle, 0) for j in lot)

    lignes = ["jour       cons  impr  \u2764  rép  vis  clic  abo"]
    for j in serie:
        c = jours.get(j, {})
        lignes.append("%-10s %4d %5d %3d %4d %4d %5d %4d" % (
            "%s %s" % (JOURS[j.weekday()], j.strftime("%d/%m")), c.get("conseils", 0), c.get("impressions", 0),
            c.get("likes_recus", 0), c.get("reponses_recues", 0), c.get("visites_profil", 0),
            c.get("clics_lien", 0), c.get("abonnes_gagnes", 0)))
    tableau = "```\n%s\n```" % "\n".join(lignes)

    champs = []
    for nom, cle in [("Conseils postés", "conseils"), ("Impressions", "impressions"),
                     ("J'aime reçus", "likes_recus"), ("Réponses reçues", "reponses_recues"),
                     ("Visites de profil", "visites_profil"), ("Clics sur le lien", "clics_lien"),
                     ("Abonnés gagnés", "abonnes_gagnes"), ("Interactions", "engagements")]:
        champs.append(_tuile(nom, fr(tot(serie, cle)), _vs(tot(serie, cle), tot(prec, cle),
                                                           "vs semaine précédente")))
    c7 = tot(serie, "conseils")
    champs.append(_tuile("Impressions par conseil", "%.1f" % (tot(serie, "impressions") / float(c7) if c7 else 0)))
    return {"title": "X — semaine du %s au %s" % (_jour_fr(serie[0]), _jour_fr(serie[-1])),
            "description": tableau, "color": 0x00BA7C, "fields": champs,
            "footer": {"text": "7 journées UTC complètes · x-suivi"}}


def conversations(snap):
    """Les marchands qui ont répondu à un conseil : la file de travail du matin."""
    utc = dt.datetime.now(dt.timezone.utc)
    ouv = [p for p in snap["posts"]
           if p["reponse_a"] and p["reponse_a"] != COMPTE and p["reponses"] > 0
           and p["date"] and _dtx(p["date"]) > utc - dt.timedelta(days=7)]
    ouv.sort(key=lambda p: _dtx(p["date"]), reverse=True)
    if not ouv:
        return None
    L = ["· @%s, le %s — %d réponse%s — [le fil](https://x.com/%s/status/%s)" % (
        p["reponse_a"], _dtx(p["date"]).strftime("%d/%m"), p["reponses"],
        "s" if p["reponses"] > 1 else "", COMPTE, p["id"]) for p in ouv[:6]]
    return {"title": "Conversations ouvertes", "color": 0xFFD400,
            "description": "\n".join(L),
            "footer": {"text": "%d conseil%s sur 7 jours" % (
                len(ouv), "s ont fait réagir" if len(ouv) > 1 else " a fait réagir")}}


def serie_abonnes(snap, hist, jours=14):
    """Le nombre d'abonnés par jour : le dernier relevé de chaque journée.
    X ne publie aucun historique, la courbe se construit relevé après relevé."""
    par_jour = {}
    for h in hist + [snap]:
        d = dt.datetime.fromisoformat(h["horodatage"]).date()
        par_jour[d] = h["abonnes"]
    gardes = sorted(par_jour)[-jours:]
    return [(j.strftime("%d/%m"), par_jour[j]) for j in gardes]


def poster(embeds, fichiers=()):
    url = json.load(open(CONF))["webhook_discord"] if os.path.exists(CONF) else os.environ.get("DISCORD_WEBHOOK")
    if not url:
        print(json.dumps(embeds, ensure_ascii=False, indent=2))
        return
    utile = {"embeds": embeds, "allowed_mentions": {"parse": []}}
    if fichiers:
        # Discord exige que chaque pièce jointe soit déclarée ici pour qu'un
        # embed puisse la viser avec attachment://
        utile["attachments"] = [{"id": i, "filename": nom}
                                for i, (nom, _) in enumerate(fichiers)]
    charge = json.dumps(utile, ensure_ascii=False)
    if not fichiers:
        r = urllib.request.Request(url, data=charge.encode(),
                                   headers={"content-type": "application/json",
                                            "user-agent": "x-suivi"})
        urllib.request.urlopen(r, timeout=30).read()
        return
    # envoi multipart : le graphique voyage avec le message, sans hébergeur
    lim = "----x-suivi-%d" % int(time.time())
    corps = b""
    corps += ("--%s\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
              "Content-Type: application/json\r\n\r\n%s\r\n" % (lim, charge)).encode("utf8")
    for i, (nom, octets) in enumerate(fichiers):
        corps += ("--%s\r\nContent-Disposition: form-data; name=\"files[%d]\"; filename=\"%s\"\r\n"
                  "Content-Type: image/png\r\n\r\n" % (lim, i, nom)).encode("utf8")
        corps += octets + b"\r\n"
    corps += ("--%s--\r\n" % lim).encode()
    r = urllib.request.Request(url, data=corps, headers={
        "content-type": "multipart/form-data; boundary=" + lim, "user-agent": "x-suivi"})
    urllib.request.urlopen(r, timeout=60).read()


def apercu(embeds):
    """Rendu texte des cartes, pour vérifier sans rien poster."""
    for e in embeds:
        print("\n=== %s ===" % e["title"])
        if e.get("description"):
            print(e["description"].replace("```", "").strip())
        for c in e.get("fields", []):
            print("%-22s %s" % (c["name"], c["value"].replace("**", "").replace("\n", " · ")))
        print("-- %s" % e["footer"]["text"])


def releve_obstine(essais=3, pause=300):
    """X limite le débit sans prévenir et renvoie des timelines tronquées.
    Plutôt que de renoncer, on laisse retomber la pression et on recommence."""
    for n in range(essais):
        try:
            return releve(forcer_cookies=(n > 0))
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403) or n == essais - 1:
                raise
            print("session X refusée (%s) — on relit les cookies dans Chrome" % e.code,
                  file=sys.stderr)
            continue
        except SystemExit as e:
            if n == essais - 1 or "cookies" in str(e):
                raise
            print("%s — nouvelle tentative dans %d min" % (e, pause // 60), file=sys.stderr)
            time.sleep(pause)


if __name__ == "__main__":
    snap = releve_obstine()
    hist = charger_hist()
    # le récap hebdo part le lundi, une fois la semaine close
    lundi = dt.date.today().weekday() == 0 or "--semaine" in sys.argv
    cartes = [carte_jour(snap, hist)]
    conv = conversations(snap)
    if conv:
        cartes.append(conv)
    if lundi:
        cartes.append(carte_semaine(snap))
    # la courbe des abonnés, jointe sous la carte du jour
    serie = serie_abonnes(snap, hist)
    fichiers = []
    if len(serie) >= 2:
        png = courbe.ligne(serie)
        if png:
            cartes[0]["image"] = {"url": "attachment://abonnes.png"}
            fichiers.append(("abonnes.png", png))
    else:
        cartes[0]["footer"]["text"] += " · la courbe des abonnés démarre au 2e relevé"
    if "--essai" in sys.argv:
        apercu(cartes)
        print("courbe : %d point(s) — %s" % (len(serie), serie))
        sys.exit()
    poster(cartes, fichiers)
    with open(HIST, "a") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    print("relevé posté (%d abonnés, %d posts suivis)" % (snap["abonnes"], len(snap["posts"])))
