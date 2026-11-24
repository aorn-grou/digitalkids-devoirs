"""Installation automatique sur PythonAnywhere (compte gratuit).

À lancer dans une console Bash de PythonAnywhere :
    python3 ~/digitalkids-devoirs/installer_pythonanywhere.py

Le script vous demande votre « API token » (onglet Account → API Token), puis :
  1. installe Flask,
  2. crée le site  https://VOTRE-NOM.pythonanywhere.com,
  3. le relie au code,
  4. le démarre.
Pour une mise à jour plus tard :  python3 ~/digitalkids-devoirs/installer_pythonanywhere.py --maj
"""
import getpass
import os
import subprocess
import sys

DOSSIER = os.path.dirname(os.path.abspath(__file__))
UTILISATEUR = getpass.getuser()
DOMAINE = f"{UTILISATEUR}.pythonanywhere.com"
PYTHON = "python310"
FICHIER_TOKEN = os.path.expanduser("~/.digitalkids_token")


def etape(t):
    print(f"\n▶ {t}")


def api():
    import requests
    token = None
    if os.path.exists(FICHIER_TOKEN):
        token = open(FICHIER_TOKEN).read().strip()
    if not token:
        print("\nCollez votre API token (PythonAnywhere → Account → onglet « API Token » → Create/Copy),")
        token = input("puis appuyez sur Entrée : ").strip()
    for hote in ("www.pythonanywhere.com", "eu.pythonanywhere.com"):
        base = f"https://{hote}/api/v0/user/{UTILISATEUR}/"
        r = requests.get(base + "webapps/", headers={"Authorization": f"Token {token}"}, timeout=30)
        if r.status_code == 200:
            with open(FICHIER_TOKEN, "w") as f:
                f.write(token)
            os.chmod(FICHIER_TOKEN, 0o600)
            s = requests.Session()
            s.headers["Authorization"] = f"Token {token}"
            return s, base, r.json()
    sys.exit("✗ Le token n'est pas accepté. Vérifiez-le dans Account → API Token et relancez le script.")


def ecrire_wsgi():
    chemin = f"/var/www/{DOMAINE.replace('.', '_')}_wsgi.py"
    contenu = (
        "# Fichier créé par installer_pythonanywhere.py (Digital Kids Devoirs)\n"
        "import sys\n"
        f"chemin = {DOSSIER!r}\n"
        "if chemin not in sys.path:\n"
        "    sys.path.insert(0, chemin)\n"
        "from app import app as application\n"
    )
    with open(chemin, "w") as f:
        f.write(contenu)
    return chemin


def main():
    maj = "--maj" in sys.argv
    print("=" * 60)
    print(" Digital Kids · Devoirs en ligne · installation PythonAnywhere")
    print("=" * 60)

    if maj:
        etape("Récupération de la dernière version depuis GitHub")
        subprocess.run(["git", "-C", DOSSIER, "pull", "--ff-only"], check=False)

    etape("Installation de Flask")
    import shutil
    py = shutil.which("python3.10") or sys.executable
    subprocess.run([py, "-m", "pip", "install", "--user", "--quiet", "Flask>=2.2"], check=False)

    etape("Connexion à votre compte PythonAnywhere")
    s, base, sites = api()
    existe = any(w.get("domain_name") == DOMAINE for w in sites)

    if not existe:
        if sites:
            print(f"✗ Votre compte gratuit a déjà un site : {sites[0].get('domain_name')}.")
            print("  Un compte gratuit n'a droit qu'à UN site. Créez un nouveau compte gratuit")
            print("  (par exemple « digitalkids ») et relancez ce script depuis ce compte.")
            sys.exit(1)
        etape(f"Création du site {DOMAINE}")
        r = s.post(base + "webapps/", data={"domain_name": DOMAINE, "python_version": PYTHON}, timeout=60)
        if r.status_code not in (200, 201):
            sys.exit(f"✗ Création impossible : {r.status_code} {r.text[:300]}")
    else:
        etape(f"Le site {DOMAINE} existe déjà : mise à jour")

    etape("Liaison du site avec le code")
    ecrire_wsgi()
    s.patch(base + f"webapps/{DOMAINE}/", data={"source_directory": DOSSIER, "working_directory": DOSSIER, "force_https": "true"}, timeout=60)
    statiques = s.get(base + f"webapps/{DOMAINE}/static_files/", timeout=30).json()
    if not any(x.get("url") == "/static/" for x in statiques):
        s.post(base + f"webapps/{DOMAINE}/static_files/", data={"url": "/static/", "path": os.path.join(DOSSIER, "static")}, timeout=30)

    etape("Démarrage du site")
    r = s.post(base + f"webapps/{DOMAINE}/reload/", timeout=120)
    if r.status_code != 200:
        print(f"  (rechargement : {r.status_code}) Allez dans l'onglet Web et cliquez sur le bouton vert Reload.")

    print("\n" + "=" * 60)
    print(" ✓ C'EST EN LIGNE !")
    print(f"   Élèves     : https://{DOMAINE}")
    print(f"   Animateur  : https://{DOMAINE}/animateur")
    print("   (à la première visite de /animateur, vous créez votre mot de passe)")
    print("=" * 60)


if __name__ == "__main__":
    main()
