"""Digital Kids Anjanahary · Devoirs en ligne
Application Flask : élèves (compte, devoirs notés sur 20), animateurs (une classe chacun),
administrateur (voit tout). Installable comme une application (PWA)."""
import calendar
import csv
import io
import json
import os
import random
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   Response, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from correction import CORRECTEURS, corriger

ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.path.join(ICI, "donnees")
DOSSIER_DEVOIRS = os.path.join(ICI, "devoirs")
os.makedirs(DONNEES, exist_ok=True)
BASE = os.path.join(DONNEES, "ecole.db")
ADMIN = "admin"  # identifiant du compte administrateur


def maintenant():
    """Date et heure exactes de Madagascar (UTC+3), quel que soit le fuseau du serveur."""
    return datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")


def cle_secrete():
    p = os.path.join(DONNEES, "secret.txt")
    if not os.path.exists(p):
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
    return open(p).read().strip()


app = Flask(__name__)
app.config.update(SECRET_KEY=cle_secrete(), SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=2 * 1024 * 1024, PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)


# ------------------------------------------------------------------ base de données
def db():
    if "db" not in g:
        g.db = sqlite3.connect(BASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def fermer_db(exc):
    d = g.pop("db", None)
    if d is not None:
        d.close()


def colonnes(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def init_db():
    con = sqlite3.connect(BASE)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS reglages (cle TEXT PRIMARY KEY, valeur TEXT);
    CREATE TABLE IF NOT EXISTS eleves (id INTEGER PRIMARY KEY AUTOINCREMENT, prenom TEXT NOT NULL,
        identifiant TEXT UNIQUE NOT NULL, code TEXT NOT NULL, niveau INTEGER NOT NULL, cree TEXT);
    CREATE TABLE IF NOT EXISTS devoirs (id TEXT PRIMARY KEY, niveau INTEGER NOT NULL, titre TEXT NOT NULL,
        semaine TEXT, contenu TEXT NOT NULL, actif INTEGER DEFAULT 1, cree TEXT);
    CREATE TABLE IF NOT EXISTS reponses (eleve_id INTEGER, devoir_id TEXT, ex_id TEXT, reponse TEXT,
        note REAL, date TEXT, PRIMARY KEY (eleve_id, devoir_id, ex_id));
    CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, eleve_id INTEGER,
        type TEXT, detail TEXT, lu INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS profs (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL,
        identifiant TEXT UNIQUE NOT NULL, mdp TEXT NOT NULL, classe TEXT NOT NULL, cree TEXT);
    CREATE TABLE IF NOT EXISTS creneaux (id INTEGER PRIMARY KEY AUTOINCREMENT, classe_id INTEGER NOT NULL,
        jour INTEGER NOT NULL, debut TEXT NOT NULL, fin TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS demandes (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, code TEXT NOT NULL,
        niveau INTEGER NOT NULL, creneau_id INTEGER, classe_id INTEGER, cree TEXT, statut TEXT DEFAULT 'attente',
        traite_par TEXT, traite_le TEXT, eleve_id INTEGER);
    CREATE TABLE IF NOT EXISTS seances (creneau_id INTEGER, date TEXT, saisi_par TEXT, saisi_le TEXT,
        PRIMARY KEY (creneau_id, date));
    CREATE TABLE IF NOT EXISTS presences (eleve_id INTEGER, creneau_id INTEGER, date TEXT, statut TEXT,
        PRIMARY KEY (eleve_id, creneau_id, date));
    """)
    # mises à jour d'une ancienne base (sans perdre les données)
    if "classe_id" not in colonnes(con, "eleves"):
        con.execute("ALTER TABLE eleves ADD COLUMN classe_id INTEGER")
    if "classe_id" not in colonnes(con, "devoirs"):
        con.execute("ALTER TABLE devoirs ADD COLUMN classe_id INTEGER")
    if "cree" not in colonnes(con, "creneaux"):
        con.execute("ALTER TABLE creneaux ADD COLUMN cree TEXT")
    if "creneau_id" not in colonnes(con, "eleves"):
        con.execute("ALTER TABLE eleves ADD COLUMN creneau_id INTEGER")
    if "oubli" not in colonnes(con, "profs"):
        con.execute("ALTER TABLE profs ADD COLUMN oubli TEXT")
    if "secours" not in colonnes(con, "profs"):
        con.execute("ALTER TABLE profs ADD COLUMN secours TEXT")
    if "lu_admin" not in colonnes(con, "journal"):
        con.execute("ALTER TABLE journal ADD COLUMN lu_admin INTEGER DEFAULT 0")
    con.commit()
    if con.execute("SELECT COUNT(*) FROM devoirs").fetchone()[0] == 0:
        importer_dossier(con, None)
    installer_classes_digital_kids(con)
    con.close()


CLASSES_DIGITAL_KIDS = [
    ("Prof Santatra", "santatra", "Classe Santatra", [(5, "08:00", "10:00"), (5, "10:00", "12:00")]),
    ("Prof Toky", "toky", "Classe Toky", [(2, "14:00", "16:00"), (5, "14:00", "16:00")]),
]


def installer_classes_digital_kids(con):
    """Une seule fois : crée les 2 animateurs de Digital Kids et leurs jours/heures de cours.
    Leur mot de passe est vide : l'administrateur le choisit dans « Animateurs & cours »."""
    if os.environ.get("DK_SANS_CLASSES") == "1":
        return
    if con.execute("SELECT 1 FROM reglages WHERE cle='classes_dk'").fetchone():
        return
    for nom, ident, classe, cours in CLASSES_DIGITAL_KIDS:
        p = con.execute("SELECT id FROM profs WHERE identifiant=?", (ident,)).fetchone()
        if p:
            pid = p[0]
        else:
            pid = con.execute("INSERT INTO profs (nom, identifiant, mdp, classe, cree) VALUES (?,?,?,?,?)",
                              (nom, ident, "", classe, maintenant())).lastrowid
            importer_dossier(con, pid)
        if not con.execute("SELECT 1 FROM creneaux WHERE classe_id=?", (pid,)).fetchone():
            for jour, debut, fin in cours:
                con.execute("INSERT INTO creneaux (classe_id, jour, debut, fin, cree) VALUES (?,?,?,?,?)", (pid, jour, debut, fin, maintenant()))
    con.execute("INSERT INTO reglages VALUES ('classes_dk', '1')")
    con.commit()


# ------------------------------------------------------------------ devoirs
def verifier_devoir(d):
    """Renvoie un message d'erreur, ou None si le devoir est valide."""
    for cle in ("id", "niveau", "titre", "exercices"):
        if cle not in d:
            return f"Il manque « {cle} » dans le fichier."
    if not re.fullmatch(r"[a-z0-9\-]{3,60}", str(d["id"])):
        return "L'id doit contenir seulement des lettres minuscules, des chiffres et des tirets."
    if not d["exercices"]:
        return "Le devoir n'a aucun exercice."
    for e in d["exercices"]:
        for cle in ("id", "titre", "type", "solution"):
            if cle not in e:
                return f"Un exercice n'a pas « {cle} »."
        if e["type"] not in CORRECTEURS:
            return f"Type d'exercice inconnu : {e['type']}."
    return None


def id_base(devoir_id):
    return re.sub(r"^c\d+-", "", devoir_id)


def enregistrer_devoir(con, d, classe_id):
    """Chaque classe a sa propre copie du devoir : l'id devient c<classe>-<id>."""
    d = dict(d)
    d["id"] = id_base(d["id"]) if classe_id is None else f"c{classe_id}-{id_base(d['id'])}"
    con.execute("""INSERT INTO devoirs (id, niveau, titre, semaine, contenu, actif, cree, classe_id) VALUES (?,?,?,?,?,1,?,?)
                   ON CONFLICT(id) DO UPDATE SET niveau=excluded.niveau, titre=excluded.titre,
                   semaine=excluded.semaine, contenu=excluded.contenu""",
                (d["id"], int(d["niveau"]), d["titre"], d.get("semaine", ""), json.dumps(d, ensure_ascii=False),
                 maintenant(), classe_id))
    return d["id"]


def importer_dossier(con, classe_id):
    n = 0
    if os.path.isdir(DOSSIER_DEVOIRS):
        for nom in sorted(os.listdir(DOSSIER_DEVOIRS)):
            if nom.endswith(".json"):
                with open(os.path.join(DOSSIER_DEVOIRS, nom), encoding="utf-8") as f:
                    d = json.load(f)
                if verifier_devoir(d) is None:
                    enregistrer_devoir(con, d, classe_id)
                    n += 1
    con.commit()
    return n


def charger_devoir(devoir_id):
    r = db().execute("SELECT * FROM devoirs WHERE id=?", (devoir_id,)).fetchone()
    if not r:
        return None, None
    return r, json.loads(r["contenu"])


def version_eleve(d):
    """Copie du devoir sans les solutions ni les corrigés (ce que voit le navigateur de l'élève)."""
    c = {k: v for k, v in d.items() if k != "exercices"}
    c["exercices"] = [{k: v for k, v in e.items() if k not in ("solution", "corrige")} for e in d["exercices"]]
    for e in c["exercices"]:
        data = e.get("data", {})
        rnd = random.Random(f"{d['id']}-{e['id']}-{session.get('eleve_id')}")
        if e["type"] == "relier":
            droite = list(data.get("droite", []))
            rnd.shuffle(droite)
            data = dict(data, droite=droite)
        e["data"] = data
    return c


def moyenne(notes):
    return round(sum(notes) / len(notes), 1) if notes else None


def meme_classe(a, b):
    return (a or 0) == (b or 0)


# ------------------------------------------------------------------ journal (rapport)
def noter(eleve_id, type_, detail=""):
    db().execute("INSERT INTO journal (date, eleve_id, type, detail) VALUES (?,?,?,?)", (maintenant(), eleve_id, type_, detail))
    db().commit()


def reglage(cle, defaut=None):
    r = db().execute("SELECT valeur FROM reglages WHERE cle=?", (cle,)).fetchone()
    return r["valeur"] if r else defaut


def inscriptions_ouvertes():
    return reglage("inscriptions", "1") == "1"


# ------------------------------------------------------------------ outils
def slug(s, n=8):
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", s.lower())[:n] or "eleve"


def nouvel_identifiant(prenom):
    base = slug(prenom)
    for _ in range(200):
        ident = f"{base}{random.randint(10, 99)}"
        if not db().execute("SELECT 1 FROM eleves WHERE identifiant=?", (ident,)).fetchone():
            return ident
    return f"{base}{secrets.randbelow(10000)}"


def chiffres(v):
    """Garde seulement les chiffres, quel que soit le clavier (chiffres arabes, pleine largeur…), sans espaces."""
    out = ""
    for ch in str(v or ""):
        if ch.isdigit():
            try:
                out += str(unicodedata.digit(ch))
            except (TypeError, ValueError):
                pass
        elif not ch.isspace():
            out += ch
    return out


def nouveau_code():
    return f"{random.randint(0, 9999):04d}"


def eleve_requis(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("eleve_id"):
            return redirect(url_for("connexion"))
        return f(*a, **k)
    return w


def animateur_requis(f):
    @wraps(f)
    def w(*a, **k):
        if session.get("role") not in ("admin", "prof"):
            return redirect(url_for("animateur_connexion"))
        if session.get("role") == "prof" and not prof_courant():
            session.clear()
            return redirect(url_for("animateur_connexion"))
        return f(*a, **k)
    return w


def admin_requis(f):
    @wraps(f)
    def w(*a, **k):
        if session.get("role") != "admin":
            abort(403)
        return f(*a, **k)
    return w


def est_admin():
    return session.get("role") == "admin"


def prof_courant():
    if session.get("role") != "prof":
        return None
    return db().execute("SELECT * FROM profs WHERE id=?", (session.get("prof_id"),)).fetchone()


def a_code_secours():
    if est_admin():
        return bool(reglage("code_secours"))
    p = prof_courant()
    return bool(p and p["secours"])


def toutes_classes():
    return db().execute("SELECT * FROM profs ORDER BY classe, nom").fetchall()


def classe_filtre():
    """Classe affichée : celle de l'animateur ; pour l'admin, celle choisie (?classe=), sinon toutes (None).
    Renvoie (mode, id) : ('toutes', None) | ('classe', id) | ('sans', None)."""
    if not est_admin():
        return ("classe", session.get("prof_id"))
    c = request.args.get("classe", "")
    if c == "0":
        return ("sans", None)
    if c.isdigit():
        return ("classe", int(c))
    return ("toutes", None)


def visible(classe_id):
    mode, cid = classe_filtre()
    if mode == "toutes":
        return True
    if mode == "sans":
        return classe_id is None
    return classe_id == cid


def peut_voir(classe_id):
    return est_admin() or classe_id == session.get("prof_id")


def nom_classes():
    return {p["id"]: p for p in toutes_classes()}


def args_classe():
    """Pour garder le filtre de classe de l'admin dans les liens et redirections."""
    c = request.args.get("classe") or request.form.get("classe_filtre")
    return {"classe": c} if est_admin() and c else {}


# ------------------------------------------------------------------ cours (créneaux) et présences
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def heure(t):
    h, m = t.split(":")
    return f"{int(h)}h" + ("" if m == "00" else m)


def aujourdhui():
    return datetime.now(timezone(timedelta(hours=3))).date()


def tous_creneaux():
    out = []
    for c in db().execute("""SELECT c.*, p.classe, p.nom FROM creneaux c JOIN profs p ON p.id = c.classe_id
                             ORDER BY p.classe, c.jour, c.debut"""):
        d = dict(c)
        d["horaire"] = f"{JOURS[d['jour']]} {heure(d['debut'])}-{heure(d['fin'])}"
        d["libelle"] = f"{d['classe']} · {d['horaire']}"
        out.append(d)
    return out


def creneau(cid):
    return next((c for c in tous_creneaux() if str(c["id"]) == str(cid)), None)


def creneaux_visibles():
    return [c for c in tous_creneaux() if visible(c["classe_id"])]


def dates_du_mois(jour, mois, jusqu_a=None):
    """Toutes les dates du mois (YYYY-MM) qui tombent ce jour de la semaine, jusqu'à aujourd'hui."""
    a, m = map(int, mois.split("-"))
    d = datetime(a, m, 1).date()
    fin = jusqu_a or aujourdhui()
    out = []
    while d.month == m:
        if d.weekday() == jour and d <= fin:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def dernieres_dates(jour, n=10):
    d = aujourdhui()
    while d.weekday() != jour:
        d -= timedelta(days=1)
    return [(d - timedelta(weeks=i)).isoformat() for i in range(n)]


def taux(presents, absents):
    return round(100 * presents / (presents + absents)) if presents + absents else None


def mois_libelle(mois):
    a, m = mois.split("-")
    return f"{MOIS[int(m) - 1]} {a}"


def date_fr(d):
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}"


app.jinja_env.filters["date_fr"] = date_fr
app.jinja_env.filters["jour_semaine"] = lambda d: datetime.strptime(d, "%Y-%m-%d").weekday()
app.jinja_env.filters["mois_libelle"] = mois_libelle
app.jinja_env.filters["heure"] = heure
app.jinja_env.globals["JOURS"] = JOURS


def semaines_du_mois(mois):
    """Les semaines du mois (lundi → dimanche) pour dessiner le calendrier de présence."""
    a, m = map(int, mois.split("-"))
    return [[(f"{a:04d}-{m:02d}-{d:02d}" if d else None) for d in sem] for sem in calendar.Calendar(0).monthdayscalendar(a, m)]


def liste_mois(n=18):
    """Les derniers mois, pour une liste de choix (le champ « mois » n'existe pas dans Safari sur Mac)."""
    d = aujourdhui().replace(day=1)
    out = []
    for _ in range(n):
        out.append((d.isoformat()[:7], mois_libelle(d.isoformat()[:7])))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


app.jinja_env.globals.update(semaines_du_mois=semaines_du_mois, liste_mois=liste_mois,
                             aujourdhui_iso=lambda: aujourdhui().isoformat())


@app.context_processor
def contexte():
    ctx = {"annee": datetime.now().year, "rapports_nouveaux": 0, "demandes_attente": 0, "role": session.get("role"), "moi": None,
           "classes": [], "classe_choisie": request.args.get("classe", "")}
    if session.get("role") in ("admin", "prof"):
        try:
            ctx["demandes_attente"] = sum(1 for d in db().execute("SELECT classe_id FROM demandes WHERE statut='attente'") if peut_voir(d["classe_id"]))
            if est_admin():
                ctx["moi"] = "Administrateur"
                ctx["classes"] = toutes_classes()
                ctx["rapports_nouveaux"] = db().execute("SELECT COUNT(*) FROM journal WHERE lu_admin=0").fetchone()[0]
            else:
                p = prof_courant()
                if p:
                    ctx["moi"] = p["nom"]
                    ctx["rapports_nouveaux"] = db().execute("""SELECT COUNT(*) FROM journal j JOIN eleves e ON e.id=j.eleve_id
                                                               WHERE j.lu=0 AND e.classe_id=?""", (p["id"],)).fetchone()[0]
        except sqlite3.Error:
            pass
    return ctx


# ------------------------------------------------------------------ application installable
@app.route("/sw.js")
def service_worker():
    r = send_from_directory(os.path.join(ICI, "static"), "sw.js", mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.route("/manifest.webmanifest")
def manifeste():
    return send_from_directory(os.path.join(ICI, "static"), "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/installer")
def installer():
    return render_template("installer.html")


# ------------------------------------------------------------------ élèves
@app.route("/")
def accueil():
    if session.get("eleve_id"):
        return redirect(url_for("mes_devoirs"))
    return redirect(url_for("connexion"))


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    erreur = None
    if request.method == "POST":
        nom = request.form.get("identifiant", "").strip()
        code = chiffres(request.form.get("code", ""))
        tentatives = session.get("tentatives", 0)
        if tentatives >= 8:
            erreur = "Trop d'essais. Demande de l'aide à l'animateur."
        else:
            cands = db().execute("SELECT * FROM eleves WHERE identifiant=? OR lower(prenom)=?", (nom.lower(), nom.lower())).fetchall()
            bons = [e for e in cands if secrets.compare_digest(e["code"], code)]
            if len(bons) == 1:
                e = bons[0]
                session.clear()
                session.permanent = True
                session["eleve_id"] = e["id"]
                noter(e["id"], "connexion", f"Niveau {e['niveau']}")
                return redirect(url_for("mes_devoirs"))
            if len(bons) > 1:
                erreur = "Plusieurs élèves ont ce prénom et ce code : écris ton identifiant (par exemple rivo25)."
            elif not bons and (dm := db().execute("SELECT * FROM demandes WHERE lower(nom)=? AND code=? AND statut!='valide' ORDER BY id DESC",
                                                  (nom.lower(), code)).fetchone()):
                erreur = ("⏳ Ta demande d'inscription attend la validation de ton professeur. Reviens plus tard !" if dm["statut"] == "attente"
                          else "Ta demande d'inscription a été refusée. Parle à ton professeur.")
            else:
                session["tentatives"] = tentatives + 1
                erreur = "Prénom ou code incorrect. Vérifie et recommence."
    return render_template("connexion.html", erreur=erreur, inscriptions=inscriptions_ouvertes())


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    """N'importe qui peut demander son inscription ; le professeur du cours choisi la valide."""
    if not inscriptions_ouvertes():
        return render_template("erreur.html", message="Les inscriptions sont fermées pour le moment. Demande à ton professeur.")
    crs = tous_creneaux()
    jours = sorted({c["jour"] for c in crs})
    erreur, valeurs = None, {}
    if request.method == "POST":
        nom_famille = re.sub(r"\s+", " ", request.form.get("nom", "")).strip()
        nom = re.sub(r"\s+", " ", (nom_famille + " " + request.form.get("prenom", "")).strip()).strip()[:60]
        code = chiffres(request.form.get("code", ""))
        code2 = chiffres(request.form.get("code2", ""))
        niveau = request.form.get("niveau", "")
        cr = creneau(request.form.get("creneau", ""))
        classe = request.form.get("classe", "")
        classe_ok = (not crs) and (classe in [str(c["id"]) for c in toutes_classes()] or not toutes_classes())
        valeurs = {"classe": classe, "prenom": request.form.get("prenom", "").strip(), "nom": nom_famille, "niveau": niveau, "creneau": request.form.get("creneau", ""), "jour": request.form.get("jour", "")}
        if "nom" in request.form and len(nom_famille) < 2:
            erreur = "Écris ton nom de famille (case « Nom », exemple : Rakoto)."
        elif "nom" in request.form and len(request.form.get("prenom", "").strip()) < 2:
            erreur = "Écris ton prénom (case « Prénom », exemple : Andry)."
        elif len(nom) < 2:
            erreur = "Écris ton nom et ton prénom (exemple : Rakoto Andry)."
        elif not re.fullmatch(r"\d{4}", code):
            erreur = ("Ton code secret doit avoir exactement 4 chiffres"
                      + (f" (la case contenait {len(code)} caractère(s) : efface-la complètement et réécris tes 4 chiffres)." if code else "."))
        elif code != code2:
            erreur = "Les deux codes ne sont pas pareils. Recommence."
        elif not cr and not classe_ok:
            erreur = "Choisis ta classe (samedi ou mercredi) et l'heure de ton cours."
        elif niveau not in ("1", "2"):
            erreur = "Choisis ton niveau."
        elif db().execute("SELECT 1 FROM demandes WHERE lower(nom)=? AND statut='attente'", (nom.lower(),)).fetchone():
            erreur = "Une demande avec ce nom attend déjà la validation du professeur. Patiente un peu !"
        elif db().execute("SELECT 1 FROM eleves WHERE lower(prenom)=? AND code=?", (nom.lower(), code)).fetchone():
            erreur = "Tu es déjà inscrit avec ce nom et ce code : connecte-toi."
        else:
            cur = db().execute("INSERT INTO demandes (nom, code, niveau, creneau_id, classe_id, cree) VALUES (?,?,?,?,?,?)",
                               (nom, code, int(niveau), cr["id"] if cr else None,
                                cr["classe_id"] if cr else (int(classe) if classe.isdigit() else None), maintenant()))
            db().commit()
            session["demande"] = cur.lastrowid
            return redirect(url_for("demande_envoyee"))
    return render_template("inscription.html", erreur=erreur, v=valeurs, creneaux=crs, jours=jours, classes=toutes_classes())


@app.route("/inscription/envoyee")
def demande_envoyee():
    d = db().execute("SELECT * FROM demandes WHERE id=?", (session.get("demande", 0),)).fetchone()
    if not d:
        return redirect(url_for("inscription"))
    return render_template("demande_envoyee.html", d=d, cr=creneau(d["creneau_id"]))


def eleve_courant():
    return db().execute("SELECT * FROM eleves WHERE id=?", (session["eleve_id"],)).fetchone()


@app.route("/bienvenue")
@eleve_requis
def bienvenue():
    e = eleve_courant()
    if not e:
        session.clear()
        return redirect(url_for("connexion"))
    p = db().execute("SELECT * FROM profs WHERE id=?", (e["classe_id"],)).fetchone() if e["classe_id"] else None
    cr = creneau(e["creneau_id"])
    return render_template("bienvenue.html", eleve=e, prof=p, cr=cr)


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("connexion"))


def devoirs_de(e):
    if e["classe_id"] is None:
        return db().execute("SELECT * FROM devoirs WHERE niveau=? AND actif=1 AND classe_id IS NULL ORDER BY cree DESC, id DESC", (e["niveau"],)).fetchall()
    return db().execute("SELECT * FROM devoirs WHERE niveau=? AND actif=1 AND classe_id=? ORDER BY cree DESC, id DESC", (e["niveau"], e["classe_id"])).fetchall()


@app.route("/mes-devoirs")
@eleve_requis
def mes_devoirs():
    e = eleve_courant()
    if not e:
        session.clear()
        return redirect(url_for("connexion"))
    devoirs = []
    for r in devoirs_de(e):
        d = json.loads(r["contenu"])
        notes = [x["note"] for x in db().execute("SELECT note FROM reponses WHERE eleve_id=? AND devoir_id=?", (e["id"], r["id"]))]
        devoirs.append({"id": r["id"], "titre": r["titre"], "semaine": r["semaine"], "total": len(d["exercices"]),
                        "faits": len(notes), "moyenne": moyenne(notes)})
    return render_template("mes_devoirs.html", eleve=e, devoirs=devoirs)


def devoir_autorise(r, e):
    return r and r["actif"] and r["niveau"] == e["niveau"] and meme_classe(r["classe_id"], e["classe_id"])


@app.route("/devoir/<devoir_id>")
@eleve_requis
def devoir(devoir_id):
    e = eleve_courant()
    r, d = charger_devoir(devoir_id)
    if not e or not devoir_autorise(r, e):
        abort(404)
    faits = {}
    for x in db().execute("SELECT * FROM reponses WHERE eleve_id=? AND devoir_id=?", (e["id"], devoir_id)):
        ex = next((y for y in d["exercices"] if y["id"] == x["ex_id"]), None)
        if ex:
            faits[x["ex_id"]] = {"note": x["note"], "corrige": ex.get("corrige", ""), "reponse": json.loads(x["reponse"])}
    return render_template("devoir.html", eleve=e, devoir=version_eleve(d), faits=faits)


@app.route("/api/valider", methods=["POST"])
@eleve_requis
def valider():
    e = eleve_courant()
    corps = request.get_json(silent=True) or {}
    r, d = charger_devoir(str(corps.get("devoir", "")))
    if not e or not devoir_autorise(r, e):
        return jsonify(erreur="Devoir introuvable."), 404
    ex = next((y for y in d["exercices"] if y["id"] == corps.get("ex")), None)
    if not ex:
        return jsonify(erreur="Exercice introuvable."), 404
    deja = db().execute("SELECT note FROM reponses WHERE eleve_id=? AND devoir_id=? AND ex_id=?", (e["id"], r["id"], ex["id"])).fetchone()
    if deja:
        note = deja["note"]
    else:
        reponse = corps.get("reponse")
        texte = json.dumps(reponse, ensure_ascii=False)
        if len(texte) > 20000:
            return jsonify(erreur="Réponse trop longue."), 400
        note = corriger(ex, reponse)
        db().execute("INSERT INTO reponses VALUES (?,?,?,?,?,?)", (e["id"], r["id"], ex["id"], texte, note, maintenant()))
        db().commit()
    notes = [x["note"] for x in db().execute("SELECT note FROM reponses WHERE eleve_id=? AND devoir_id=?", (e["id"], r["id"]))]
    if not deja:
        if len(notes) == 1:
            noter(e["id"], "debut", r["titre"])
        noter(e["id"], "exercice", f"{r['titre']} · {ex['titre']} : {note}/20")
        if len(notes) == len(d["exercices"]):
            noter(e["id"], "fini", f"{r['titre']} · moyenne {moyenne(notes)}/20")
    return jsonify(note=note, corrige=ex.get("corrige", ""), faits=len(notes), total=len(d["exercices"]), moyenne=moyenne(notes))


# ------------------------------------------------------------------ connexion animateur / admin
@app.route("/animateur", methods=["GET", "POST"])
def animateur_connexion():
    hache = reglage("mot_de_passe")
    erreur = None
    if request.method == "POST":
        ident = request.form.get("identifiant", ADMIN).strip().lower() or ADMIN
        mdp = request.form.get("mot_de_passe", "")
        if not hache:  # premier lancement : création du compte administrateur
            if len(mdp) < 6 or mdp != request.form.get("confirmation", ""):
                erreur = "Le mot de passe doit avoir au moins 6 caractères, écrit 2 fois pareil."
            else:
                db().execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (generate_password_hash(mdp),))
                db().commit()
                session.clear()
                session.permanent = True
                session["role"] = "admin"
                return redirect(url_for("tableau_de_bord"))
        elif ident == ADMIN:
            if check_password_hash(hache, mdp):
                session.clear()
                session.permanent = True
                session["role"] = "admin"
                return redirect(url_for("tableau_de_bord"))
            erreur = "Identifiant ou mot de passe incorrect."
        else:
            p = db().execute("SELECT * FROM profs WHERE identifiant=?", (ident,)).fetchone()
            if p and not p["mdp"]:
                erreur = "Le mot de passe de cet animateur n'est pas encore choisi. L'administrateur doit le choisir dans « Animateurs & cours »."
            elif p and check_password_hash(p["mdp"], mdp):
                session.clear()
                session.permanent = True
                session["role"] = "prof"
                session["prof_id"] = p["id"]
                return redirect(url_for("tableau_de_bord"))
            else:
                erreur = "Identifiant ou mot de passe incorrect."
    return render_template("animateur_connexion.html", premier=not hache, erreur=erreur)


@app.route("/animateur/oubli", methods=["GET", "POST"])
def mot_de_passe_oublie():
    """Mot de passe oublié : identifiant + code de secours + nouveau mot de passe."""
    erreur = None
    if request.method == "POST":
        ident = request.form.get("identifiant", "").strip().lower()
        code = request.form.get("secours", "").strip()
        mdp = request.form.get("mot_de_passe", "")
        essais = session.get("essais_secours", 0)
        if essais >= 5:
            erreur = "Trop d'essais. Réessayez plus tard."
        elif len(mdp) < 6 or mdp != request.form.get("confirmation", ""):
            erreur = "Le nouveau mot de passe doit avoir au moins 6 caractères, écrit 2 fois pareil."
        else:
            if ident == ADMIN:
                h = reglage("code_secours")
            else:
                p = db().execute("SELECT * FROM profs WHERE identifiant=?", (ident,)).fetchone()
                h = p["secours"] if p else None
            if h and check_password_hash(h, code.lower()):
                nouveau = generate_password_hash(mdp)
                if ident == ADMIN:
                    db().execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (nouveau,))
                else:
                    db().execute("UPDATE profs SET mdp=? WHERE identifiant=?", (nouveau, ident))
                db().commit()
                session.pop("essais_secours", None)
                flash("✅ Mot de passe changé. Connectez-vous avec votre nouveau mot de passe.")
                return redirect(url_for("animateur_connexion"))
            session["essais_secours"] = essais + 1
            erreur = "Identifiant ou code de secours incorrect."
    return render_template("oubli.html", erreur=erreur)


# ------------------------------------------------------------------ tableau des notes
@app.route("/animateur/tableau")
@animateur_requis
def tableau():
    eleves = [e for e in db().execute("SELECT * FROM eleves ORDER BY niveau, prenom") if visible(e["classe_id"])]
    devoirs = [d for d in db().execute("SELECT id, niveau, titre, semaine, actif, contenu, classe_id FROM devoirs ORDER BY niveau, cree DESC") if visible(d["classe_id"])]
    notes = {}
    for x in db().execute("SELECT eleve_id, devoir_id, COUNT(*) n, AVG(note) m FROM reponses GROUP BY eleve_id, devoir_id"):
        notes[(x["eleve_id"], x["devoir_id"])] = (x["n"], round(x["m"], 1))
    nb_ex = {d["id"]: len(json.loads(d["contenu"])["exercices"]) for d in devoirs}
    derniere = {x["eleve_id"]: x["d"] for x in db().execute("SELECT eleve_id, MAX(date) d FROM journal WHERE type IN ('connexion','inscription') GROUP BY eleve_id")}
    ids = {e["id"] for e in eleves}
    recents = [l for l in db().execute("""SELECT j.*, e.prenom FROM journal j LEFT JOIN eleves e ON e.id = j.eleve_id
                                          ORDER BY j.id DESC LIMIT 200""") if l["eleve_id"] in ids][:8]
    # groupes : une section par classe puis par niveau
    cls = nom_classes()
    groupes = []
    cles = sorted({(e["classe_id"], e["niveau"]) for e in eleves}, key=lambda k: (cls[k[0]]["classe"] if k[0] in cls else "~", k[1]))
    for cid, niv in cles:
        titre = (f"{cls[cid]['classe']} · {cls[cid]['nom']}" if cid in cls else "Sans classe") + f" · Niveau {niv}"
        groupes.append({"titre": titre, "eleves": [e for e in eleves if e["classe_id"] == cid and e["niveau"] == niv],
                        "devoirs": [d for d in devoirs if d["classe_id"] == cid and d["niveau"] == niv]})
    return render_template("tableau.html", groupes=groupes, eleves=eleves, notes=notes, nb_ex=nb_ex, recents=recents,
                           derniere=derniere, inscriptions=inscriptions_ouvertes())


# ------------------------------------------------------------------ animateurs (admin)
@app.route("/animateur/profs", methods=["GET", "POST"])
@animateur_requis
@admin_requis
def profs():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "ajouter":
            nom = request.form.get("nom", "").strip()[:60]
            classe = request.form.get("classe", "").strip()[:60]
            mdp = request.form.get("mot_de_passe", "")
            ident = slug(request.form.get("identifiant", "") or nom, 20)
            if not nom or not classe:
                flash("Écrivez le nom de l'animateur et le nom de sa classe.")
            elif len(mdp) < 6:
                flash("Le mot de passe de l'animateur doit avoir au moins 6 caractères.")
            elif ident == ADMIN or db().execute("SELECT 1 FROM profs WHERE identifiant=?", (ident,)).fetchone():
                flash(f"L'identifiant « {ident} » existe déjà. Choisissez-en un autre.")
            else:
                cur = db().execute("INSERT INTO profs (nom, identifiant, mdp, classe, cree) VALUES (?,?,?,?,?)",
                                   (nom, ident, generate_password_hash(mdp), classe, maintenant()))
                n = importer_dossier(db(), cur.lastrowid)
                db().commit()
                flash(f"Animateur « {nom} » créé (identifiant : {ident}). Sa classe a reçu {n} devoir(s). Ajoutez maintenant ses jours et heures de cours.")
        elif action == "mdp":
            mdp = request.form.get("mot_de_passe", "")
            if len(mdp) < 6:
                flash("Le mot de passe doit avoir au moins 6 caractères.")
            else:
                db().execute("UPDATE profs SET mdp=?, oubli=NULL WHERE id=?", (generate_password_hash(mdp), request.form["prof"]))
                db().commit()
                flash("Mot de passe de l'animateur changé. Donnez-lui son identifiant et ce mot de passe.")
        elif action == "creneau":
            jour, debut, fin = request.form.get("jour", ""), request.form.get("debut", ""), request.form.get("fin", "")
            pid = request.form.get("prof", "")
            if not (jour.isdigit() and 0 <= int(jour) <= 6 and re.fullmatch(r"\d{2}:\d{2}", debut) and re.fullmatch(r"\d{2}:\d{2}", fin) and debut < fin and pid.isdigit()):
                flash("Choisissez le jour, l'heure de début et l'heure de fin.")
            elif db().execute("SELECT 1 FROM creneaux WHERE classe_id=? AND jour=? AND debut=?", (pid, jour, debut)).fetchone():
                flash("Ce cours existe déjà.")
            else:
                db().execute("INSERT INTO creneaux (classe_id, jour, debut, fin, cree) VALUES (?,?,?,?,?)", (int(pid), int(jour), debut, fin, maintenant()))
                db().commit()
                flash(f"Cours ajouté : {JOURS[int(jour)]} {heure(debut)}-{heure(fin)}.")
        elif action == "creneau_supprimer":
            cid = int(request.form["creneau"])
            if db().execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=?", (cid,)).fetchone()[0]:
                flash("Ce cours a encore des élèves : changez-les de cours d'abord.")
            else:
                db().execute("DELETE FROM creneaux WHERE id=?", (cid,))
                db().execute("DELETE FROM seances WHERE creneau_id=?", (cid,))
                db().execute("DELETE FROM presences WHERE creneau_id=?", (cid,))
                db().commit()
                flash("Cours supprimé.")
        elif action == "supprimer":
            pid = int(request.form["prof"])
            if db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id=?", (pid,)).fetchone()[0]:
                flash("Cette classe a encore des élèves : déplacez-les ou supprimez-les d'abord.")
            else:
                for d in db().execute("SELECT id FROM devoirs WHERE classe_id=?", (pid,)).fetchall():
                    db().execute("DELETE FROM reponses WHERE devoir_id=?", (d["id"],))
                for c in db().execute("SELECT id FROM creneaux WHERE classe_id=?", (pid,)).fetchall():
                    db().execute("DELETE FROM seances WHERE creneau_id=?", (c["id"],))
                    db().execute("DELETE FROM presences WHERE creneau_id=?", (c["id"],))
                db().execute("DELETE FROM creneaux WHERE classe_id=?", (pid,))
                db().execute("DELETE FROM devoirs WHERE classe_id=?", (pid,))
                db().execute("DELETE FROM profs WHERE id=?", (pid,))
                db().commit()
                flash("Animateur et classe supprimés.")
        return redirect(url_for("profs"))
    crs = tous_creneaux()
    liste = []
    for p in toutes_classes():
        liste.append({"p": p, "eleves": db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id=?", (p["id"],)).fetchone()[0],
                      "devoirs": db().execute("SELECT COUNT(*) FROM devoirs WHERE classe_id=?", (p["id"],)).fetchone()[0],
                      "creneaux": [dict(c, eleves=db().execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=?", (c["id"],)).fetchone()[0])
                                   for c in crs if c["classe_id"] == p["id"]]})
    sans = db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id IS NULL").fetchone()[0]
    return render_template("profs.html", profs=liste, sans_classe=sans, jours=JOURS)


# ------------------------------------------------------------------ élèves (animateur)
def ajouter_eleve(nom, niveau, cr=None, classe_id=None):
    """Ajoute un élève ; s'il existe déjà dans la classe (même nom), on le met seulement dans ce cours. Renvoie (eleve_id, nouveau)."""
    classe_id = cr["classe_id"] if cr else classe_id
    nom = re.sub(r"\s+", " ", nom).strip()[:60]
    deja = db().execute("SELECT * FROM eleves WHERE lower(prenom)=? AND classe_id IS ?", (nom.lower(), classe_id)).fetchone()
    if deja:
        if cr:
            db().execute("UPDATE eleves SET creneau_id=? WHERE id=?", (cr["id"], deja["id"]))
        if niveau:
            db().execute("UPDATE eleves SET niveau=? WHERE id=?", (niveau, deja["id"]))
        return deja["id"], False
    cur = db().execute("INSERT INTO eleves (prenom, identifiant, code, niveau, cree, classe_id, creneau_id) VALUES (?,?,?,?,?,?,?)",
                       (nom, nouvel_identifiant(nom), nouveau_code(), niveau or 1, maintenant(), classe_id, cr["id"] if cr else None))
    return cur.lastrowid, True


@app.route("/animateur/eleves", methods=["GET", "POST"])
@animateur_requis
def eleves():
    crs = creneaux_visibles()
    if request.method == "POST":
        if not est_admin():
            abort(403)
        if request.form.get("action") == "placer":
            cr = creneau(request.form.get("creneau", ""))
            e = db().execute("SELECT * FROM eleves WHERE id=?", (request.form.get("eleve", ""),)).fetchone()
            if cr and e:
                db().execute("UPDATE eleves SET creneau_id=?, classe_id=? WHERE id=?", (cr["id"], cr["classe_id"], e["id"]))
                db().commit()
                flash(f"{e['prenom']} est maintenant dans le cours {cr['libelle']}.")
            return redirect(url_for("eleves", **args_classe()))
        niveau = int(request.form.get("niveau", "1"))
        cr = creneau(request.form.get("creneau", ""))
        c = request.form.get("classe", "")
        classe_id = int(c) if c.isdigit() else None
        n = m = 0
        for ligne in request.form.get("prenoms", "").splitlines():
            if ligne.strip():
                _, nouveau = ajouter_eleve(ligne, niveau, cr, classe_id)
                n += nouveau
                m += not nouveau
        db().commit()
        if n or m:
            flash(f"{n} élève(s) ajouté(s)" + (f", {m} déjà inscrit(s) mis dans ce cours" if m else "") + ". Leurs identifiants et codes sont dans la liste.")
        return redirect(url_for("eleves", **args_classe()))
    liste = [e for e in db().execute("SELECT * FROM eleves ORDER BY lower(prenom)") if visible(e["classe_id"])]
    par_cours = [{"c": c, "eleves": [e for e in liste if e["creneau_id"] == c["id"]]} for c in crs]
    a_placer = [e for e in liste if e["creneau_id"] not in {c["id"] for c in crs}]
    tous = tous_creneaux() if est_admin() else crs
    return render_template("eleves.html", eleves=liste, par_cours=par_cours, a_placer=a_placer, tous_cours=tous, noms=nom_classes())


def valider_demande(d, cr, niveau, qui):
    """Inscrit l'élève de la demande (ou le relie à un élève déjà écrit par l'administrateur avec le même nom)."""
    eid, nouveau = ajouter_eleve(d["nom"], niveau, cr, d["classe_id"])
    db().execute("UPDATE eleves SET code=? WHERE id=?", (d["code"], eid))
    db().execute("UPDATE demandes SET statut='valide', traite_par=?, traite_le=?, eleve_id=?, creneau_id=?, niveau=? WHERE id=?",
                 (qui, maintenant(), eid, cr["id"] if cr else None, niveau, d["id"]))
    db().execute("INSERT INTO journal (date, eleve_id, type, detail) VALUES (?,?,?,?)",
                 (maintenant(), eid, "inscription", f"Inscription validée par {qui} · " + (cr["horaire"] if cr else "sans cours") + f" · niveau {niveau}"))
    return eid


@app.route("/animateur/demandes", methods=["GET", "POST"])
@animateur_requis
def demandes():
    qui = "Administrateur" if est_admin() else prof_courant()["nom"]
    if request.method == "POST":
        action = request.form.get("action")
        ids = request.form.getlist("demande") if action == "tout" else [request.form.get("demande", "")]
        n = 0
        for i in ids:
            d = db().execute("SELECT * FROM demandes WHERE id=? AND statut='attente'", (i,)).fetchone()
            if not d or not peut_voir(d["classe_id"]):
                continue
            if action == "refuser":
                db().execute("UPDATE demandes SET statut='refuse', traite_par=?, traite_le=? WHERE id=?", (qui, maintenant(), d["id"]))
                flash(f"Demande de {d['nom']} refusée.")
                continue
            cr = creneau(request.form.get(f"creneau_{d['id']}") or d["creneau_id"])
            if not cr or not peut_voir(cr["classe_id"]):
                cr = creneau(d["creneau_id"])
            niv = request.form.get(f"niveau_{d['id']}", str(d["niveau"]))
            valider_demande(d, cr, int(niv) if niv in ("1", "2") else d["niveau"], qui)
            n += 1
        db().commit()
        if n:
            flash(f"✅ {n} élève(s) inscrit(s). Ils peuvent se connecter et sont sur la fiche d'appel.")
        return redirect(url_for("demandes", **args_classe()))
    tout = [d for d in db().execute("SELECT * FROM demandes ORDER BY id DESC LIMIT 300") if visible(d["classe_id"])]
    noms_cr = {c["id"]: c for c in tous_creneaux()}
    mes_cours = [c for c in noms_cr.values() if peut_voir(c["classe_id"])]
    return render_template("demandes.html", attente=[d for d in tout if d["statut"] == "attente"][::-1],
                           traitees=[d for d in tout if d["statut"] != "attente"][:30], noms_cr=noms_cr, mes_cours=mes_cours)


@app.route("/animateur/inserer", methods=["GET", "POST"])
@animateur_requis
@admin_requis
def inserer():
    """Page simple pour l'administrateur : coller la liste des élèves de chaque animateur."""
    if request.method == "POST":
        cr = creneau(request.form.get("creneau", ""))
        niveau = int(request.form.get("niveau", "1")) if request.form.get("niveau") in ("1", "2") else 1
        if not cr:
            flash("Choisissez le jour et l'heure du cours.")
            return redirect(url_for("inserer"))
        n = m = 0
        for ligne in request.form.get("prenoms", "").splitlines():
            if ligne.strip(" -•\t0123456789.)"):
                _, nouveau = ajouter_eleve(ligne.strip(" -•\t").lstrip("0123456789.) ").strip() or ligne, niveau, cr)
                n += nouveau
                m += not nouveau
        db().commit()
        flash(f"{cr['nom']} · {cr['horaire']} · niveau {niveau} : {n} élève(s) ajouté(s)" + (f", {m} déjà dans la liste" if m else "") + ".")
        return redirect(url_for("inserer", fait=cr["id"]))
    crs = tous_creneaux()
    profs_ = []
    for p in toutes_classes():
        cours = [dict(c, n1=db().execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=? AND niveau=1", (c["id"],)).fetchone()[0],
                      n2=db().execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=? AND niveau=2", (c["id"],)).fetchone()[0])
                 for c in crs if c["classe_id"] == p["id"]]
        if cours:
            profs_.append({"p": p, "cours": cours})
    return render_template("inserer.html", profs=profs_, fait=request.args.get("fait", ""))


@app.route("/animateur/eleve/<int:eid>", methods=["GET", "POST"])
@animateur_requis
def eleve_detail(eid):
    e = db().execute("SELECT * FROM eleves WHERE id=?", (eid,)).fetchone()
    if not e or not peut_voir(e["classe_id"]):
        abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "niveau":
            db().execute("UPDATE eleves SET niveau=? WHERE id=?", (int(request.form["niveau"]), eid))
            flash("Niveau changé.")
        elif action == "nom" and est_admin():
            nom = re.sub(r"\s+", " ", request.form.get("prenom", "")).strip()[:60]
            if nom:
                db().execute("UPDATE eleves SET prenom=? WHERE id=?", (nom, eid))
                flash("Nom changé.")
        elif action == "classe" and est_admin():
            c = request.form.get("classe", "")
            db().execute("UPDATE eleves SET classe_id=?, creneau_id=NULL WHERE id=?", (int(c) if c.isdigit() else None, eid))
            flash("Classe changée.")
        elif action == "creneau" and est_admin():
            cr = creneau(request.form.get("creneau", ""))
            if cr:
                db().execute("UPDATE eleves SET creneau_id=?, classe_id=? WHERE id=?", (cr["id"], cr["classe_id"], eid))
            else:
                db().execute("UPDATE eleves SET creneau_id=NULL WHERE id=?", (eid,))
            flash("Classe et jour de cours changés.")
        elif action == "code":
            db().execute("UPDATE eleves SET code=? WHERE id=?", (nouveau_code(), eid))
            flash("Nouveau code créé.")
        elif action == "reset":
            db().execute("DELETE FROM reponses WHERE eleve_id=? AND devoir_id=?", (eid, request.form["devoir"]))
            flash("Le devoir est remis à zéro pour cet élève.")
        elif action == "supprimer" and est_admin():
            for t in ("reponses", "journal", "presences"):
                db().execute(f"DELETE FROM {t} WHERE eleve_id=?", (eid,))
            db().execute("DELETE FROM eleves WHERE id=?", (eid,))
            db().commit()
            flash("Élève supprimé.")
            return redirect(url_for("eleves"))
        db().commit()
        return redirect(url_for("eleve_detail", eid=eid))
    resultats = []
    for r in db().execute("SELECT * FROM devoirs ORDER BY cree DESC"):
        reps = {x["ex_id"]: x for x in db().execute("SELECT * FROM reponses WHERE eleve_id=? AND devoir_id=?", (eid, r["id"]))}
        if not reps and (r["niveau"] != e["niveau"] or not meme_classe(r["classe_id"], e["classe_id"])):
            continue
        d = json.loads(r["contenu"])
        lignes = [{"titre": x["titre"], "note": reps[x["id"]]["note"] if x["id"] in reps else None,
                   "date": reps[x["id"]]["date"] if x["id"] in reps else ""} for x in d["exercices"]]
        resultats.append({"id": r["id"], "titre": r["titre"], "lignes": lignes,
                          "moyenne": moyenne([l["note"] for l in lignes if l["note"] is not None])})
    connexions = db().execute("SELECT date, type FROM journal WHERE eleve_id=? AND type IN ('connexion','inscription') ORDER BY id DESC LIMIT 15", (eid,)).fetchall()
    prof = db().execute("SELECT * FROM profs WHERE id=?", (e["classe_id"],)).fetchone() if e["classe_id"] else None
    noms_cr = {c["id"]: c for c in tous_creneaux()}
    pres = db().execute("SELECT * FROM presences WHERE eleve_id=? ORDER BY date DESC", (eid,)).fetchall()
    par_mois = {}
    for x in pres:
        m = par_mois.setdefault(x["date"][:7], {"mois": x["date"][:7], "P": 0, "R": 0, "A": 0, "dates": []})
        m[x["statut"]] += 1
        m["dates"].append(x)
        m.setdefault("par_date", {})[x["date"]] = x["statut"]
    mois = list(par_mois.values())
    for m in mois:
        m["taux"] = taux(m["P"] + m["R"], m["A"])
    tot = {k: sum(m[k] for m in mois) for k in "PRA"}
    return render_template("eleve_detail.html", e=e, resultats=resultats, connexions=connexions, prof=prof,
                           cr=noms_cr.get(e["creneau_id"]), noms_cr=noms_cr, mois_pres=mois,
                           taux_total=taux(tot["P"] + tot["R"], tot["A"]), tot=tot)


@app.route("/animateur/fiches")
@animateur_requis
def fiches():
    liste = [e for e in db().execute("SELECT * FROM eleves ORDER BY classe_id, niveau, prenom") if visible(e["classe_id"])]
    return render_template("fiches.html", eleves=liste, noms=nom_classes(), adresse=request.host_url.rstrip("/"))


# ------------------------------------------------------------------ devoirs (animateur)
@app.route("/animateur/devoirs", methods=["GET", "POST"])
@animateur_requis
def devoirs_admin():
    if request.method == "POST":
        action = request.form.get("action")
        if est_admin():
            c = request.form.get("cible", "")
            cibles = [p["id"] for p in toutes_classes()] if c == "toutes" else ([int(c)] if c.isdigit() else [None])
        else:
            cibles = [session["prof_id"]]
        if action == "televerser":
            f = request.files.get("fichier")
            try:
                d = json.load(io.TextIOWrapper(f.stream, encoding="utf-8"))
                err = verifier_devoir(d)
            except Exception:
                err = "Ce fichier n'est pas un devoir valide (format JSON)."
            if err:
                flash("Erreur : " + err)
            else:
                for cid in cibles:
                    enregistrer_devoir(db(), d, cid)
                db().commit()
                flash(f"Devoir « {d['titre']} » ajouté pour le niveau {d['niveau']} ({len(cibles)} classe(s)).")
        elif action == "importer":
            n = sum(importer_dossier(db(), cid) for cid in cibles)
            flash(f"{n} devoir(s) importé(s) depuis le dossier devoirs/.")
        elif action in ("actif", "supprimer"):
            r = db().execute("SELECT * FROM devoirs WHERE id=?", (request.form["devoir"],)).fetchone()
            if r and peut_voir(r["classe_id"]):
                if action == "actif":
                    db().execute("UPDATE devoirs SET actif = 1 - actif WHERE id=?", (r["id"],))
                else:
                    db().execute("DELETE FROM reponses WHERE devoir_id=?", (r["id"],))
                    db().execute("DELETE FROM devoirs WHERE id=?", (r["id"],))
                    flash("Devoir supprimé.")
                db().commit()
        return redirect(url_for("devoirs_admin", **args_classe()))
    cls = nom_classes()
    liste = []
    for r in db().execute("SELECT * FROM devoirs ORDER BY classe_id, niveau, cree DESC"):
        if not visible(r["classe_id"]):
            continue
        d = json.loads(r["contenu"])
        n = db().execute("SELECT COUNT(DISTINCT eleve_id) FROM reponses WHERE devoir_id=?", (r["id"],)).fetchone()[0]
        liste.append({"r": r, "nb": len(d["exercices"]), "eleves": n,
                      "classe": (cls[r["classe_id"]]["classe"] if r["classe_id"] in cls else "Sans classe")})
    return render_template("devoirs_admin.html", devoirs=liste)


@app.route("/animateur/apercu/<devoir_id>")
@animateur_requis
def apercu(devoir_id):
    r, d = charger_devoir(devoir_id)
    if not r or not peut_voir(r["classe_id"]):
        abort(404)
    return render_template("devoir.html", eleve=None, devoir=version_eleve(d), faits={}, apercu=True,
                           corriges={e["id"]: e.get("corrige", "") for e in d["exercices"]})


# ------------------------------------------------------------------ rapport
@app.route("/animateur/rapports")
@animateur_requis
def rapports():
    jour = request.args.get("jour") or maintenant()[:10]
    cls = nom_classes()
    lignes = [l for l in db().execute("""SELECT j.*, e.prenom, e.identifiant, e.niveau, e.code, e.classe_id FROM journal j
                                         LEFT JOIN eleves e ON e.id = j.eleve_id WHERE substr(j.date,1,10)=? ORDER BY j.id DESC""", (jour,))
              if l["prenom"] is not None and visible(l["classe_id"])]
    resume = {}
    for l in reversed(lignes):
        r = resume.setdefault(l["eleve_id"], {"prenom": l["prenom"], "identifiant": l["identifiant"], "code": l["code"],
                                              "niveau": l["niveau"], "premiere": l["date"], "derniere": l["date"],
                                              "exercices": 0, "fini": None, "id": l["eleve_id"],
                                              "classe": cls[l["classe_id"]]["classe"] if l["classe_id"] in cls else "Sans classe"})
        r["derniere"] = l["date"]
        if l["type"] == "exercice":
            r["exercices"] += 1
        elif l["type"] == "fini":
            r["fini"] = (l["date"], l["detail"])
    jours = [x[0] for x in db().execute("SELECT DISTINCT substr(date,1,10) FROM journal ORDER BY 1 DESC LIMIT 30")]
    page = render_template("rapports.html", lignes=lignes, resume=list(resume.values()), jour=jour, jours=jours, noms=cls)
    if est_admin():
        db().execute("UPDATE journal SET lu_admin=1 WHERE lu_admin=0")
    else:
        db().execute("UPDATE journal SET lu=1 WHERE lu=0 AND eleve_id IN (SELECT id FROM eleves WHERE classe_id=?)", (session["prof_id"],))
    db().commit()
    return page


@app.route("/animateur/inscriptions", methods=["POST"])
@animateur_requis
@admin_requis
def basculer_inscriptions():
    db().execute("INSERT OR REPLACE INTO reglages VALUES ('inscriptions', ?)", ("0" if inscriptions_ouvertes() else "1",))
    db().commit()
    flash("Inscriptions " + ("ouvertes : les élèves peuvent créer leur compte." if inscriptions_ouvertes() else "fermées."))
    return redirect(url_for("tableau"))


@app.route("/animateur/notes.csv")
@animateur_requis
def notes_csv():
    cls = nom_classes()
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Classe", "Prénom", "Identifiant", "Code", "Niveau", "Devoir", "Exercice", "Note /20", "Date"])
    for x in db().execute("""SELECT e.prenom, e.identifiant, e.code, e.niveau, e.classe_id, r.devoir_id, r.ex_id, r.note, r.date
                             FROM reponses r JOIN eleves e ON e.id = r.eleve_id ORDER BY e.classe_id, e.niveau, e.prenom, r.devoir_id, r.ex_id"""):
        if visible(x["classe_id"]):
            w.writerow([cls[x["classe_id"]]["classe"] if x["classe_id"] in cls else "Sans classe", x["prenom"], x["identifiant"], x["code"],
                        x["niveau"], id_base(x["devoir_id"]), x["ex_id"], str(x["note"]).replace(".", ","), x["date"]])
    return Response("﻿" + sortie.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=notes-digital-kids.csv"})


@app.route("/animateur/mot-de-passe", methods=["GET", "POST"])
@animateur_requis
def mot_de_passe():
    if request.method == "POST" and request.form.get("action") == "secours":
        code = request.form.get("secours", "").strip()
        if len(code) < 4:
            flash("Le code de secours doit avoir au moins 4 caractères.")
        else:
            h = generate_password_hash(code.lower())
            if est_admin():
                db().execute("INSERT OR REPLACE INTO reglages VALUES ('code_secours', ?)", (h,))
            else:
                db().execute("UPDATE profs SET secours=? WHERE id=?", (h, session["prof_id"]))
            db().commit()
            flash("✅ Code de secours enregistré. Notez-le bien : il sert si vous oubliez votre mot de passe.")
        return redirect(url_for("mot_de_passe"))
    if request.method == "POST":
        mdp = request.form.get("mot_de_passe", "")
        if len(mdp) < 6 or mdp != request.form.get("confirmation", ""):
            flash("Le mot de passe doit avoir au moins 6 caractères, écrit 2 fois pareil.")
        else:
            if est_admin():
                db().execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (generate_password_hash(mdp),))
            else:
                db().execute("UPDATE profs SET mdp=? WHERE id=?", (generate_password_hash(mdp), session["prof_id"]))
            db().commit()
            flash("Mot de passe changé.")
            return redirect(url_for("tableau"))
    return render_template("mot_de_passe.html", a_secours=a_code_secours())


@app.route("/animateur/deconnexion")
def animateur_deconnexion():
    session.clear()
    return redirect(url_for("animateur_connexion"))


# ------------------------------------------------------------------ tableau de bord
def calcul_presences(crs, mois):
    """Pour chaque cours : séances du mois, fiches faites, et pour chaque élève présences / absences / taux."""
    out = []
    for c in crs:
        depuis = (c.get("cree") or "0000")[:10]
        dates = [d for d in dates_du_mois(c["jour"], mois) if d >= depuis]
        faites = {x["date"]: x for x in db().execute("SELECT * FROM seances WHERE creneau_id=? AND substr(date,1,7)=?", (c["id"], mois))}
        statuts = {}
        for x in db().execute("SELECT * FROM presences WHERE creneau_id=? AND substr(date,1,7)=?", (c["id"], mois)):
            statuts[(x["eleve_id"], x["date"])] = x["statut"]
        for d in faites:
            if d not in dates:
                dates.append(d)
        dates.sort()
        ids = [e["id"] for e in db().execute("SELECT id FROM eleves WHERE creneau_id=?", (c["id"],))]
        ids += [i for (i, _) in statuts if i not in ids]
        lignes = []
        for i in dict.fromkeys(ids):
            e = db().execute("SELECT * FROM eleves WHERE id=?", (i,)).fetchone()
            if not e:
                continue
            cases = [statuts.get((i, d), "?" if d in faites else "") for d in dates]
            p = sum(1 for x in cases if x in ("P", "R"))
            a = cases.count("A")
            lignes.append({"e": e, "cases": cases, "par_date": dict(zip(dates, cases)), "presents": p, "retards": cases.count("R"), "absents": a, "taux": taux(p, a),
                           "parti": e["creneau_id"] != c["id"]})
        lignes.sort(key=lambda l: (l["parti"], l["e"]["prenom"].lower()))
        out.append({"c": c, "dates": dates, "faites": faites, "lignes": lignes,
                    "a_faire": [d for d in dates if d not in faites and d < aujourdhui().isoformat()]})
    return out


@app.route("/animateur/accueil")
@animateur_requis
def tableau_de_bord():
    mois = aujourdhui().isoformat()[:7]
    crs = creneaux_visibles()
    pres = calcul_presences(crs, mois)
    eleves_ = [e for e in db().execute("SELECT * FROM eleves") if visible(e["classe_id"])]
    ids = {e["id"] for e in eleves_}
    jour = aujourdhui().weekday()
    auj = aujourdhui().isoformat()
    du_jour = [{"c": c, "faite": db().execute("SELECT 1 FROM seances WHERE creneau_id=? AND date=?", (c["id"], auj)).fetchone() is not None,
                "eleves": db().execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=?", (c["id"],)).fetchone()[0]}
               for c in crs if c["jour"] == jour]
    tp = sum(l["presents"] for x in pres for l in x["lignes"])
    ta = sum(l["absents"] for x in pres for l in x["lignes"])
    absents = sorted([(l, x["c"]) for x in pres for l in x["lignes"] if l["absents"] >= 2 and not l["parti"]],
                     key=lambda t: -t[0]["absents"])
    en_retard = [(x["c"], d) for x in pres for d in x["a_faire"]]
    classes = []
    for p in toutes_classes():
        if not visible(p["id"]):
            continue
        lp = [l for x in pres if x["c"]["classe_id"] == p["id"] for l in x["lignes"]]
        classes.append({"p": p, "eleves": sum(1 for e in eleves_ if e["classe_id"] == p["id"]),
                        "cours": [x for x in crs if x["classe_id"] == p["id"]],
                        "taux": taux(sum(l["presents"] for l in lp), sum(l["absents"] for l in lp))})
    finis = sum(1 for x in db().execute("SELECT eleve_id FROM journal WHERE type='fini' AND substr(date,1,7)=?", (mois,)) if x["eleve_id"] in ids)
    notes = [x["note"] for x in db().execute("SELECT eleve_id, note FROM reponses WHERE substr(date,1,7)=?", (mois,)) if x["eleve_id"] in ids]
    recents = [l for l in db().execute("""SELECT j.*, e.prenom FROM journal j LEFT JOIN eleves e ON e.id = j.eleve_id
                                          ORDER BY j.id DESC LIMIT 300""") if l["eleve_id"] in ids][:6]
    sans_cours = sum(1 for e in eleves_ if not e["creneau_id"])
    return render_template("tableau_de_bord.html", a_secours=a_code_secours(), mois=mois, nb_eleves=len(eleves_), taux_mois=taux(tp, ta), du_jour=du_jour,
                           absents=absents[:10], en_retard=en_retard, stats_classes=classes, finis=finis, moyenne_mois=moyenne(notes),
                           recents=recents, sans_cours=sans_cours, nb_cours=len(crs), aujourdhui=auj)


# ------------------------------------------------------------------ fiche de présence
@app.route("/animateur/presence", methods=["GET", "POST"])
@animateur_requis
def presence():
    crs = creneaux_visibles()
    cr = creneau(request.values.get("creneau", ""))
    if cr and not peut_voir(cr["classe_id"]):
        abort(404)
    if not cr:
        jour = aujourdhui().weekday()
        return render_template("presence.html", crs=crs, cr=None, jour=jour)
    dates = dernieres_dates(cr["jour"])
    date = request.values.get("date") or dates[0]
    try:
        ok_date = datetime.strptime(date, "%Y-%m-%d").date().weekday() == cr["jour"] and date <= aujourdhui().isoformat()
    except ValueError:
        ok_date = False
    if not ok_date:
        flash(f"Ce cours a lieu le {JOURS[cr['jour']].lower()} : choisissez une date dans la liste.")
        return redirect(url_for("presence", creneau=cr["id"]))
    if date not in dates:
        dates.append(date)
        dates.sort(reverse=True)
    eleves_ = db().execute("SELECT * FROM eleves WHERE creneau_id=? ORDER BY lower(prenom)", (cr["id"],)).fetchall()
    if request.method == "POST":
        n = {"P": 0, "A": 0, "R": 0}
        for e in eleves_:
            st = request.form.get(f"e{e['id']}", "")
            if st in n:
                db().execute("INSERT OR REPLACE INTO presences VALUES (?,?,?,?)", (e["id"], cr["id"], date, st))
                n[st] += 1
        qui = "Administrateur" if est_admin() else prof_courant()["nom"]
        db().execute("INSERT OR REPLACE INTO seances VALUES (?,?,?,?)", (cr["id"], date, qui, maintenant()))
        db().commit()
        flash(f"Fiche du {date_fr(date)} enregistrée : {n['P']} présent(s), {n['R']} en retard, {n['A']} absent(s).")
        return redirect(url_for("presence", creneau=cr["id"], date=date))
    statuts = {x["eleve_id"]: x["statut"] for x in db().execute("SELECT * FROM presences WHERE creneau_id=? AND date=?", (cr["id"], date))}
    seance = db().execute("SELECT * FROM seances WHERE creneau_id=? AND date=?", (cr["id"], date)).fetchone()
    return render_template("presence.html", crs=crs, cr=cr, dates=dates, date=date, eleves=eleves_, statuts=statuts, seance=seance)


@app.route("/animateur/presences")
@animateur_requis
def rapport_presence():
    mois = request.args.get("mois") or aujourdhui().isoformat()[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", mois):
        mois = aujourdhui().isoformat()[:7]
    vue = request.args.get("vue") if request.args.get("vue") in ("calendrier", "tableau") else "mois"
    q = request.args.get("q", "").strip()
    if vue == "mois":
        return render_template("rapport_presence.html", mois=mois, vue=vue, q=q, **rapport_mensuel(mois, q))
    pres = calcul_presences(creneaux_visibles(), mois)
    return render_template("rapport_presence.html", pres=pres, mois=mois, vue=vue, q=q)


def rapport_mensuel(mois, q=""):
    """Un seul tableau : tous les élèves × tous les jours du mois (✓ présent, ✗ absent)."""
    a, m = map(int, mois.split("-"))
    nb = calendar.monthrange(a, m)[1]
    jours = [{"d": f"{a:04d}-{m:02d}-{j:02d}", "n": j, "js": datetime(a, m, j).weekday()} for j in range(1, nb + 1)]
    noms_cr = {c["id"]: c for c in tous_creneaux()}
    statuts = {}
    for x in db().execute("SELECT eleve_id, date, statut FROM presences WHERE substr(date,1,7)=?", (mois,)):
        statuts.setdefault(x["eleve_id"], {})[x["date"]] = x["statut"]
    jours_faits = {x["date"] for x in db().execute("SELECT date FROM seances WHERE substr(date,1,7)=?", (mois,))}
    cle = slug(q, 100) if q else ""
    lignes = []
    for e in db().execute("SELECT * FROM eleves ORDER BY lower(prenom)"):
        if not visible(e["classe_id"]) or (not e["creneau_id"] and e["id"] not in statuts):
            continue
        if cle and cle not in slug(e["prenom"], 100):
            continue
        st = statuts.get(e["id"], {})
        cr = noms_cr.get(e["creneau_id"])
        cases = [{"st": st.get(j["d"], ""), "cours": bool(cr and cr["jour"] == j["js"])} for j in jours]
        p = sum(1 for c in cases if c["st"] in ("P", "R"))
        ab = sum(1 for c in cases if c["st"] == "A")
        lignes.append({"e": e, "cr": cr, "cases": cases, "presents": p, "absents": ab, "taux": taux(p, ab), "cle": slug(e["prenom"], 100)})
    lignes.sort(key=lambda l: ((l["cr"] or {}).get("classe", "~"), (l["cr"] or {}).get("jour", 9), (l["cr"] or {}).get("debut", ""), l["e"]["prenom"].lower()))
    ids = {l["e"]["id"]: l for l in lignes}
    pointages = []
    for x in db().execute("""SELECT p.eleve_id, p.creneau_id, p.date, p.statut, s.saisi_par, s.saisi_le FROM presences p
                             LEFT JOIN seances s ON s.creneau_id = p.creneau_id AND s.date = p.date
                             WHERE substr(p.date,1,7)=? ORDER BY p.date DESC""", (mois,)):
        if x["eleve_id"] in ids:
            l = ids[x["eleve_id"]]
            pointages.append({"date": x["date"], "statut": x["statut"], "e": l["e"], "cle": l["cle"],
                              "cr": noms_cr.get(x["creneau_id"]), "par": x["saisi_par"] or "", "le": x["saisi_le"] or ""})
    pointages.sort(key=lambda t: (t["date"], t["e"]["prenom"].lower()), reverse=True)
    return {"jours": jours, "lignes": lignes, "jours_faits": jours_faits, "pointages": pointages}


# ------------------------------------------------------------------ recherche
@app.route("/animateur/recherche")
@animateur_requis
def recherche():
    q = request.args.get("q", "").strip()
    res = []
    if q:
        cle = slug(q, 100)
        noms_cr = {c["id"]: c for c in tous_creneaux()}
        cls = nom_classes()
        for e in db().execute("SELECT * FROM eleves ORDER BY lower(prenom)"):
            if not peut_voir(e["classe_id"]):
                continue
            if cle in slug(e["prenom"], 100) or q.lower() == e["identifiant"]:
                notes = [x["note"] for x in db().execute("SELECT note FROM reponses WHERE eleve_id=?", (e["id"],))]
                st = [x["statut"] for x in db().execute("SELECT statut FROM presences WHERE eleve_id=?", (e["id"],))]
                p = sum(1 for x in st if x in "PR")
                res.append({"e": e, "cr": noms_cr.get(e["creneau_id"]), "classe": cls.get(e["classe_id"]),
                            "moyenne": moyenne(notes), "presents": p, "absents": st.count("A"), "taux": taux(p, st.count("A"))})
        if len(res) == 1:
            return redirect(url_for("eleve_detail", eid=res[0]["e"]["id"]))
    return render_template("recherche.html", q=q, res=res)


# ------------------------------------------------------------------ Excel
def nom_feuille(txt, pris):
    t = re.sub(r"[\[\]:*?/\\]", "", txt)[:31]
    base, i = t, 2
    while t in pris:
        t = f"{base[:28]} {i}"
        i += 1
    pris.add(t)
    return t


def classeur_presences(pres, mois):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    trait = Side(style="thin", color="7A8BB0")
    bord = Border(left=trait, right=trait, top=trait, bottom=trait)
    entete = PatternFill("solid", fgColor="0B47C4")
    pris = set()
    if not pres:
        ws = wb.create_sheet("Aucun cours")
        ws["A1"] = "Aucun cours n'est encore créé. Menu « Animateurs & classes » → ajouter les jours et heures."
    for x in pres:
        c = x["c"]
        ws = wb.create_sheet(nom_feuille(f"{c['classe']} {JOURS[c['jour']][:3]} {heure(c['debut'])}-{heure(c['fin'])}", pris))
        dates = x["dates"] or dates_du_mois(c["jour"], mois, jusqu_a=datetime(9999, 1, 1).date())
        ws["A1"] = f"Fiche de présence · {c['classe']} · {c['nom']} · {c['horaire']} · {mois_libelle(mois)}   [#{c['id']}]"
        ws["A1"].font = Font(bold=True, size=14, color="062A78")
        ws["A2"] = "P = présent · R = retard · A = absent. Une lettre par case. Pour ajouter un élève : écrivez son nom sur une nouvelle ligne, puis importez le fichier dans le site (menu Excel)."
        ws["A2"].font = Font(italic=True, size=9)
        tetes = ["N°", "Prénom et nom", "Niveau", "Identifiant", "Code"] + [date_fr(d) for d in dates] + ["Présences", "Absences", "Taux"]
        for j, t in enumerate(tetes, 1):
            cell = ws.cell(row=4, column=j, value=t)
            cell.font, cell.fill, cell.border = Font(bold=True, color="FFFFFF"), entete, bord
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        lignes = x["lignes"] or [None] * 0
        d1, d2 = get_column_letter(6), get_column_letter(5 + len(dates))
        for i, l in enumerate(lignes, 1):
            r = 4 + i
            e = l["e"]
            vals = [i, e["prenom"], e["niveau"], e["identifiant"], e["code"]] + [v if v in ("P", "A", "R") else "" for v in l["cases"]]
            for j, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=j, value=v)
                cell.border = bord
                if j >= 6:
                    cell.alignment = Alignment(horizontal="center")
            k = 6 + len(dates)
            if dates:
                ws.cell(row=r, column=k, value=f'=COUNTIF({d1}{r}:{d2}{r},"P")+COUNTIF({d1}{r}:{d2}{r},"R")')
                ws.cell(row=r, column=k + 1, value=f'=COUNTIF({d1}{r}:{d2}{r},"A")')
                ws.cell(row=r, column=k + 2, value=f'=IFERROR({get_column_letter(k)}{r}/({get_column_letter(k)}{r}+{get_column_letter(k + 1)}{r}),"")')
                ws.cell(row=r, column=k + 2).number_format = "0%"
            for j in range(k, k + 3):
                ws.cell(row=r, column=j).border = bord
                ws.cell(row=r, column=j).font = Font(bold=True)
        for j, w in enumerate([5, 28, 8, 12, 8] + [11] * len(dates) + [11, 10, 8], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.row_dimensions[4].height = 30
        ws.freeze_panes = "C5"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.fitToHeight = 0
    return wb


def envoyer_classeur(wb, nom):
    sortie = io.BytesIO()
    wb.save(sortie)
    return Response(sortie.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={nom}"})


@app.route("/animateur/excel")
@animateur_requis
def excel():
    return render_template("excel.html", mois=aujourdhui().isoformat()[:7], crs=creneaux_visibles())


@app.route("/animateur/excel/presences.xlsx")
@animateur_requis
def excel_presences():
    mois = request.args.get("mois") or aujourdhui().isoformat()[:7]
    if not re.fullmatch(r"\d{4}-\d{2}", mois):
        abort(404)
    pres = calcul_presences(creneaux_visibles(), mois)
    return envoyer_classeur(classeur_presences(pres, mois), f"presences-{mois}.xlsx")


@app.route("/animateur/excel/notes.xlsx")
@animateur_requis
def excel_notes():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes"
    cls = nom_classes()
    noms_cr = {c["id"]: c for c in tous_creneaux()}
    ws.append(["Classe", "Cours", "Prénom et nom", "Identifiant", "Niveau", "Devoir", "Exercices faits", "Moyenne /20"])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0B47C4")
    for x in db().execute("""SELECT e.id, e.prenom, e.identifiant, e.niveau, e.classe_id, e.creneau_id, d.titre, COUNT(*) n, AVG(r.note) m
                             FROM reponses r JOIN eleves e ON e.id = r.eleve_id JOIN devoirs d ON d.id = r.devoir_id
                             GROUP BY e.id, r.devoir_id ORDER BY e.classe_id, e.prenom"""):
        if visible(x["classe_id"]):
            ws.append([cls[x["classe_id"]]["classe"] if x["classe_id"] in cls else "Sans classe",
                       noms_cr[x["creneau_id"]]["horaire"] if x["creneau_id"] in noms_cr else "",
                       x["prenom"], x["identifiant"], x["niveau"], x["titre"], x["n"], round(x["m"], 1)])
    for col, w in zip("ABCDEFGH", [16, 20, 28, 12, 8, 40, 14, 12]):
        ws.column_dimensions[col].width = w
    return envoyer_classeur(wb, "notes.xlsx")


# ------------------------------------------------------------------ import intelligent : VOS fichiers Excel → le logiciel
DOSSIER_IMPORTS = os.path.join(DONNEES, "imports")
MOTS_NOM = ("nometprenom", "prenometnom", "nomprenom", "prenomnom", "nomcomplet", "nomsetprenoms", "eleve", "eleves", "enfant",
            "enfants", "apprenant", "etudiant", "name", "noms", "nom", "prenom", "prenoms", "fanampinanarana", "anarana")
MOTS_PRENOM = ("prenom", "prenoms", "fanampinanarana")
MOTS_NIVEAU = ("niveau", "niv", "level", "nivo")
MOTS_COURS = ("cours", "jour", "jours", "horaire", "heure", "heures", "creneau", "seance", "groupe", "classe", "prof", "professeur",
              "animateur", "formateur", "enseignant", "mpampianatra", "andro", "ora")
STATUT_P = ("p", "present", "presente", "presents", "x", "1", "oui", "ok", "v", "pr", "eny", "tonga")
STATUT_A = ("a", "absent", "absente", "absents", "abs", "0", "non", "tsy", "tsytonga")
STATUT_R = ("r", "retard", "enretard", "late", "tara")
JOURS_SLUG = {"lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
              "alatsinainy": 0, "talata": 1, "alarobia": 2, "alakamisy": 3, "zoma": 4, "asabotsy": 5, "alahady": 6}


def lire_statut(v):
    if v is None or v == "":
        return None
    brut = str(v).strip()
    if brut in ("✓", "✔", "☑", "👍", "+"):
        return "P"
    if brut in ("✗", "✘", "❌", "-", "×"):
        return "A"
    t = re.sub(r"[^a-z0-9]", "", "".join(ch for ch in unicodedata.normalize("NFD", brut.lower()) if unicodedata.category(ch) != "Mn"))
    if not t:
        return None
    if t in STATUT_P:
        return "P"
    if t in STATUT_A:
        return "A"
    if t in STATUT_R:
        return "R"
    return None


def lire_date(v, annee=None):
    """Une date dans une case Excel : vraie date, « 04/11/2026 », « 4/11 », « Mer 04-11-26 »…"""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if hasattr(v, "isoformat") and not isinstance(v, (str, int, float)):
        return v.isoformat()[:10]
    t = str(v or "").strip()
    m = re.search(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", t)
    if m:
        a, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?(?!\d)", t)
        if not m or len(t) > 30:
            return None
        j, mo = int(m.group(1)), int(m.group(2))
        a = int(m.group(3)) if m.group(3) else (annee or aujourdhui().year)
        if a < 100:
            a += 2000
    try:
        return datetime(a, mo, j).date().isoformat()
    except ValueError:
        return None


def trouver_cours(texte, crs):
    """Reconnaît un cours dans un texte libre : « Samedi 8h », « sam 10h-12h Santatra », « Toky mercredi »…"""
    if not str(texte or "").strip():
        return None
    t = slug(str(texte), 200)
    sans_accents = "".join(ch for ch in unicodedata.normalize("NFD", str(texte).lower()) if unicodedata.category(ch) != "Mn")
    mots = re.findall(r"[a-z]+", sans_accents)
    jour = next((JOURS_SLUG[w] for w in mots if w in JOURS_SLUG), None)
    if jour is None:  # abréviations : « mer », « sam », « asab »…
        jour = next((n for w in mots if len(w) >= 3 for k, n in JOURS_SLUG.items() if k.startswith(w)), None)
    heures = [int(h) for h in re.findall(r"(?<!\d)(\d{1,2})\s*(?:h|:|heures?)", str(texte).lower())]
    meilleurs, score_max = [], 0
    for c in crs:
        sc = 0
        if jour is not None:
            sc += 3 if c["jour"] == jour else -5
        if heures:  # la 1re heure écrite est l'heure de début (« 8h-10h » = cours de 8h)
            h = int(c["debut"][:2])
            sc += 4 if h == heures[0] else (1 if h in heures else (-2 if jour is not None else 0))
        nom_prof = slug(c["nom"].replace("Prof", ""), 40)
        if nom_prof and nom_prof in t:
            sc += 2
        if slug(c["classe"], 40) and slug(c["classe"], 40) in t:
            sc += 1
        if sc > score_max:
            meilleurs, score_max = [c], sc
        elif sc == score_max and sc > 0:
            meilleurs.append(c)
    return meilleurs[0] if len(meilleurs) == 1 and score_max >= 3 else None


def lire_fichier(chemin):
    """Renvoie [(nom_feuille, lignes)] pour un .xlsx, .xlsm ou .csv."""
    if chemin.endswith(".csv"):
        brut = open(chemin, "rb").read()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texte = brut.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialecte = csv.Sniffer().sniff(texte[:4000], delimiters=";,\t")
        except csv.Error:
            dialecte = csv.excel
        return [("CSV", [list(r) for r in csv.reader(io.StringIO(texte), dialecte)])]
    from openpyxl import load_workbook
    wb = load_workbook(chemin, data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        lignes = []
        for i, r in enumerate(ws.iter_rows(values_only=True)):
            if i > 3000:
                break
            lignes.append(list(r))
        while lignes and not any(v not in (None, "") for v in lignes[-1]):
            lignes.pop()
        out.append((ws.title, lignes))
    wb.close()
    return out


def analyser_feuille(titre, lignes, crs):
    """Devine les colonnes d'une feuille : nom (et prénom), niveau, cours, dates de présence."""
    largeur = max((len(l) for l in lignes), default=0)
    lignes = [list(l) + [None] * (largeur - len(l)) for l in lignes]
    def s_(v):
        t = "".join(ch for ch in unicodedata.normalize("NFD", str(v if v is not None else "")) if unicodedata.category(ch) != "Mn")
        return re.sub(r"[^a-z]", "", t.lower())[:40]
    entete = None
    for i, l in enumerate(lignes[:20]):
        if any(s_(v) in MOTS_NOM for v in l):
            entete = i
            break
    if entete is None:  # pas de titre de colonne : la colonne qui a le plus de mots
        entete = -1
    tete = lignes[entete] if entete >= 0 else [None] * largeur
    corps = [l for l in lignes[entete + 1:] if any(v not in (None, "") for v in l)]
    cols_nom = [j for j, v in enumerate(tete) if s_(v) in MOTS_NOM]
    col_prenom = next((j for j in cols_nom if s_(tete[j]) in MOTS_PRENOM and len(cols_nom) > 1), None)
    col_nom = next((j for j in cols_nom if j != col_prenom), None)
    if col_nom is None:
        scores = [(sum(1 for l in corps[:50] if isinstance(l[j], str) and re.search(r"[A-Za-zÀ-ÿ]{2}", l[j]) and not lire_date(l[j])
                       and lire_statut(l[j]) is None and not trouver_cours(l[j], crs)), j) for j in range(largeur)]
        col_nom = max(scores)[1] if scores and max(scores)[0] else None
    col_niv = next((j for j, v in enumerate(tete) if s_(v) in MOTS_NIVEAU or s_(v).startswith("niveau")), None)
    col_cours = next((j for j, v in enumerate(tete) if s_(v) in MOTS_COURS and j not in (col_nom, col_prenom, col_niv)), None)
    if col_cours is None:  # « Jour de cours », « Horaire du cours », « Nom du prof »…
        col_cours = next((j for j, v in enumerate(tete) if j not in (col_nom, col_prenom, col_niv) and s_(v) and not lire_date(v)
                          and any(k in s_(v) for k in ("jour", "cours", "horaire", "heure", "creneau", "seance", "groupe", "classe", "prof", "animateur", "formateur", "andro"))), None)
    annee = None
    for l in lignes[:max(entete, 0) + 1]:
        for v in l:
            m = re.search(r"(20\d\d)", str(v or ""))
            if m:
                annee = int(m.group(1))
                break
    dates = [(j, lire_date(v, annee)) for j, v in enumerate(tete) if j not in (col_nom, col_prenom, col_niv, col_cours) and lire_date(v, annee)]
    # le cours de toute la feuille : repère [#id] du modèle, sinon le titre de la feuille ou le texte au-dessus du tableau
    haut = " ".join(str(v) for l in lignes[:max(entete, 1)] for v in l if v)
    m = re.search(r"\[#(\d+)\]", haut)
    cours_feuille = (creneau(m.group(1)) if m else None) or trouver_cours(titre, crs) or trouver_cours(haut, crs)
    return {"titre": titre, "tete": tete, "corps": corps, "largeur": largeur, "col_nom": col_nom, "col_prenom": col_prenom,
            "col_niv": col_niv, "col_cours": col_cours, "dates": dates, "cours": cours_feuille}


def lettre(j):
    from openpyxl.utils import get_column_letter
    return get_column_letter(j + 1)


def lignes_a_importer(a, reglage_, crs):
    """Applique les choix de l'administrateur : renvoie [{nom, niveau, cours, pointages}]."""
    cn, cp, cv, cc = reglage_["col_nom"], reglage_["col_prenom"], reglage_["col_niv"], reglage_["col_cours"]
    out = []
    for l in a["corps"]:
        nom = str(l[cn]).strip() if cn is not None and l[cn] not in (None, "") else ""
        if cp is not None and l[cp] not in (None, ""):
            nom = (nom + " " + str(l[cp]).strip()).strip()
        nom = re.sub(r"^\s*(\d+\s*[.)\-]\s*|[-•]\s*)", "", nom).strip()
        if not nom or nom.startswith("=") or len(nom) < 2 or not re.search(r"[A-Za-zÀ-ÿ]", nom) or slug(nom, 40) in ("total", "totaux", "moyenne"):
            continue
        niv = reglage_["niveau"]
        if cv is not None:
            m = re.search(r"[123]", str(l[cv] or ""))
            if m:
                niv = int(m.group())
        cr = (trouver_cours(l[cc], crs) if cc is not None else None) or reglage_["cours"]
        pts = [(d, lire_statut(l[j])) for j, d in a["dates"] if lire_statut(l[j])]
        out.append({"nom": nom[:60], "niveau": niv, "cours": cr, "pointages": pts})
    return out


def chemin_import(jeton):
    if not re.fullmatch(r"[0-9a-f]{32}\.(xlsx|xlsm|csv)", jeton or ""):
        return None
    p = os.path.join(DOSSIER_IMPORTS, jeton)
    return p if os.path.exists(p) else None


@app.route("/animateur/excel/importer", methods=["POST"])
@animateur_requis
@admin_requis
def excel_importer():
    f = request.files.get("fichier")
    nom = (f.filename or "").lower() if f else ""
    ext = nom.rsplit(".", 1)[-1] if "." in nom else ""
    if ext == "xls":
        flash("Ce fichier est un ancien Excel (.xls). Ouvrez-le dans Excel, puis Fichier → Enregistrer sous → « Classeur Excel (.xlsx) », et recommencez.")
        return redirect(url_for("excel"))
    if ext not in ("xlsx", "xlsm", "csv"):
        flash("Choisissez un fichier Excel (.xlsx) ou CSV.")
        return redirect(url_for("excel"))
    os.makedirs(DOSSIER_IMPORTS, exist_ok=True)
    for vieux in os.listdir(DOSSIER_IMPORTS):  # ménage : fichiers de plus d'un jour
        p = os.path.join(DOSSIER_IMPORTS, vieux)
        if os.path.getmtime(p) < datetime.now().timestamp() - 86400:
            os.remove(p)
    jeton = f"{secrets.token_hex(16)}.{ext}"
    f.save(os.path.join(DOSSIER_IMPORTS, jeton))
    try:
        lire_fichier(os.path.join(DOSSIER_IMPORTS, jeton))
    except Exception:
        os.remove(os.path.join(DOSSIER_IMPORTS, jeton))
        flash("Le logiciel n'arrive pas à lire ce fichier. Enregistrez-le en « Classeur Excel (.xlsx) » et recommencez.")
        return redirect(url_for("excel"))
    session["import_nom"] = f.filename
    return redirect(url_for("excel_apercu", f=jeton))


@app.route("/animateur/excel/apercu", methods=["GET", "POST"])
@animateur_requis
@admin_requis
def excel_apercu():
    jeton = request.values.get("f", "")
    chemin = chemin_import(jeton)
    if not chemin:
        flash("Le fichier n'est plus là : choisissez-le de nouveau.")
        return redirect(url_for("excel"))
    crs = tous_creneaux()
    feuilles = [analyser_feuille(t, l, crs) for t, l in lire_fichier(chemin)]

    def choix(i, a):
        """Les réglages d'une feuille : ceux du formulaire s'il a été envoyé, sinon ceux devinés."""
        if request.values.get("modif"):
            v = lambda k: request.values.get(f"{k}_{i}", "")
            col = lambda k: int(v(k)) if v(k).isdigit() and int(v(k)) < a["largeur"] else None
            return {"importer": v("importer") == "1", "col_nom": col("col_nom"), "col_prenom": col("col_prenom"), "col_niv": col("col_niv"),
                    "col_cours": col("col_cours"), "niveau": int(v("niveau")) if v("niveau") in ("1", "2") else 1, "cours": creneau(v("cours"))}
        return {"importer": a["col_nom"] is not None and bool(a["corps"]), "col_nom": a["col_nom"], "col_prenom": a["col_prenom"],
                "col_niv": a["col_niv"], "col_cours": a["col_cours"], "niveau": 1, "cours": a["cours"]}

    resultats = []
    for i, a in enumerate(feuilles):
        r = choix(i, a)
        r["lignes"] = lignes_a_importer(a, r, crs) if r["col_nom"] is not None else []
        r["sans_cours"] = sum(1 for x in r["lignes"] if not x["cours"])
        r["nb_pointages"] = sum(len(x["pointages"]) for x in r["lignes"])
        resultats.append(r)

    if request.method == "POST" and request.form.get("action") == "importer":
        nouveaux = connus = marques = places = 0
        for a, r in zip(feuilles, resultats):
            if not r["importer"]:
                continue
            for x in r["lignes"]:
                eid, nouveau = ajouter_eleve(x["nom"], x["niveau"], x["cours"])
                nouveaux += nouveau
                connus += not nouveau
                places += bool(x["cours"])
                if x["cours"]:
                    for d, st in x["pointages"]:
                        db().execute("INSERT OR REPLACE INTO presences VALUES (?,?,?,?)", (eid, x["cours"]["id"], d, st))
                        db().execute("INSERT OR IGNORE INTO seances VALUES (?,?,?,?)", (x["cours"]["id"], d, "Import Excel", maintenant()))
                        marques += 1
        db().commit()
        os.remove(chemin)
        sans = nouveaux + connus - places
        flash(f"✅ Import terminé : {nouveaux} élève(s) ajouté(s), {connus} déjà connu(s) mis à jour, {marques} pointage(s) enregistré(s)."
              + (f" {sans} élève(s) sans cours : placez-les dans « Élèves par cours »." if sans else ""))
        return redirect(url_for("eleves"))
    return render_template("excel_apercu.html", jeton=jeton, nom_fichier=session.get("import_nom", "votre fichier"),
                           feuilles=list(zip(feuilles, resultats)), crs=crs, lettre=lettre)


@app.errorhandler(404)
def introuvable(e):
    return render_template("erreur.html", message="Cette page n'existe pas."), 404


@app.errorhandler(403)
def interdit(e):
    return render_template("erreur.html", message="Cette page est réservée à l'administrateur."), 403


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
