"""Extrait les cookies x.com du profil Chrome (macOS, chiffrement v10 Keychain)."""
import sqlite3, subprocess, hashlib, os, shutil, tempfile, json

CHROME = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/Cookies")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")

def _key():
    pw = subprocess.check_output(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"]).strip()
    return hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", 1003, 16)

def _decrypt(blob, key):
    if not blob or blob[:3] != b"v10":
        return blob.decode("utf8", "ignore")
    out = subprocess.run(
        ["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", "20" * 16, "-nopad"],
        input=blob[3:], capture_output=True).stdout
    out = out[:-out[-1]] if out and out[-1] <= 16 else out          # padding PKCS7
    try:
        return out.decode("utf8")
    except UnicodeDecodeError:
        return out[32:].decode("utf8", "ignore")                    # préfixe hash de domaine

def x_cookies(names=("auth_token", "ct0"), forcer=False):
    """Les cookies, depuis le cache local si possible.

    Déchiffrer le fichier de Chrome exige le trousseau macOS, qui peut réclamer
    une autorisation à l'écran — impossible pour une tâche de 9h du matin. On
    ne le sollicite donc qu'à la première fois, puis quand X refuse la session
    (`forcer=True`). Les cookies X vivent plusieurs mois.
    """
    if not forcer and os.path.exists(CACHE):
        try:
            got = json.load(open(CACHE))
            if all(n in got for n in names):
                return got
        except Exception:
            pass
    got = _depuis_chrome(names)
    if got:
        with open(CACHE, "w") as f:
            json.dump(got, f)
        os.chmod(CACHE, 0o600)
    return got


def _depuis_chrome(names=("auth_token", "ct0")):
    tmp = tempfile.mktemp()
    shutil.copy2(CHROME, tmp)
    key = _key()
    got = {}
    try:
        db = sqlite3.connect(tmp)
        q = ("select name, encrypted_value from cookies where host_key like '%x.com'"
             " and name in (" + ",".join("?" * len(names)) + ")")
        for name, val in db.execute(q, names):
            v = _decrypt(val, key)
            if v:
                got[name] = v
        db.close()
    finally:
        os.remove(tmp)
    return got

if __name__ == "__main__":
    for k, v in x_cookies().items():
        print(k, len(v), v[:6] + "…")
