"""Un petit graphique en PNG, dessiné aux couleurs de Discord.

Rendu en double résolution puis réduit : Discord affiche l'image à sa taille
logique, le trait et le texte restent nets.
"""
import io
from PIL import Image, ImageDraw, ImageFont

PANNEAU = (30, 31, 34)      # un cran plus sombre que le fond des embeds
TRAIT = (66, 175, 250)      # le bleu de X, éclairci pour ressortir
HALO = (36, 66, 92)         # le remplissage sous la courbe
GRILLE = (60, 63, 68)
TEXTE = (155, 162, 172)
VIF = (245, 246, 248)
POLICE = "/System/Library/Fonts/Supplemental/Arial.ttf"
POLICE_GRASSE = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _police(chemin, taille):
    try:
        return ImageFont.truetype(chemin, taille)
    except Exception:
        return ImageFont.load_default()


def ligne(points, largeur=560, hauteur=170, k=2):
    """points = [(étiquette, valeur), …] dans l'ordre chronologique."""
    if not points:
        return None
    L, H = largeur * k, hauteur * k
    im = Image.new("RGB", (L, H), PANNEAU)
    d = ImageDraw.Draw(im)
    petite, grasse = _police(POLICE, 11 * k), _police(POLICE_GRASSE, 15 * k)

    vals = [v for _, v in points]
    bas, haut = min(vals), max(vals)
    if haut == bas:                       # une courbe plate a besoin d'air
        haut, bas = haut + 1, max(0, bas - 1)
    x0, x1 = 40 * k, L - 14 * k
    y0, y1 = 22 * k, H - 26 * k

    def xy(i, v):
        x = x0 if len(points) == 1 else x0 + (x1 - x0) * i / float(len(points) - 1)
        return x, y1 - (y1 - y0) * (v - bas) / float(haut - bas)

    for n in range(3):                    # trois repères horizontaux
        v = bas + (haut - bas) * n / 2.0
        y = y1 - (y1 - y0) * n / 2.0
        d.line([(x0, y), (x1, y)], fill=GRILLE, width=k)
        d.text((6 * k, y - 7 * k), "%d" % round(v), font=petite, fill=TEXTE)

    pts = [xy(i, v) for i, (_, v) in enumerate(points)]
    if len(pts) > 1:
        d.polygon([(pts[0][0], y1)] + pts + [(pts[-1][0], y1)], fill=HALO)
        d.line(pts, fill=TRAIT, width=3 * k, joint="curve")
    for x, y in pts:
        r = 3.5 * k
        d.ellipse([x - r, y - r, x + r, y + r], fill=TRAIT, outline=PANNEAU, width=k)

    # la dernière valeur, en évidence au-dessus de son point
    xf, yf = pts[-1]
    txt = str(vals[-1])
    lt = d.textlength(txt, font=grasse)
    d.text((min(xf - lt / 2, L - lt - 2 * k), max(yf - 24 * k, 2 * k)), txt, font=grasse, fill=VIF)

    # étiquettes de dates : la première, la dernière, et une au milieu
    idx = {0, len(points) - 1} | ({len(points) // 2} if len(points) > 2 else set())
    for i in sorted(idx):
        x, _ = xy(i, vals[i])
        lt = d.textlength(points[i][0], font=petite)
        d.text((min(max(x - lt / 2, 2 * k), L - lt - 2 * k), H - 18 * k),
               points[i][0], font=petite, fill=TEXTE)

    im = im.resize((largeur, hauteur), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
