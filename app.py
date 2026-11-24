"""Digital Kids Anjanahary · Devoirs en ligne
Application Flask : élèves (compte, devoirs notés sur 20), animateurs (une classe chacun),
administrateur (voit tout). Installable comme une application (PWA)."""
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
    """)
    # mises à jour d'une ancienne base (sans perdre les données)
    if "classe_id" not in colonnes(con, "eleves"):
        con.execute("ALTER TABLE eleves ADD COLUMN classe_id INTEGER")
    if "classe_id" not in colonnes(con, "devoirs"):
        con.execute("ALTER TABLE devoirs ADD COLUMN classe_id INTEGER")
    if "lu_admin" not in colonnes(con, "journal"):
        con.execute("ALTER TABLE journal ADD COLUMN lu_admin INTEGER DEFAULT 0")
    con.commit()
    if con.execute("SELECT COUNT(*) FROM devoirs").fetchone()[0] == 0:
        importer_dossier(con, None)
    con.close()


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


@app.context_processor
def contexte():
    ctx = {"annee": datetime.now().year, "rapports_nouveaux": 0, "role": session.get("role"), "moi": None,
           "classes": [], "classe_choisie": request.args.get("classe", "")}
    if session.get("role") in ("admin", "prof"):
        try:
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
        code = request.form.get("code", "").strip()
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
            else:
                session["tentatives"] = tentatives + 1
                erreur = "Prénom ou code incorrect. Vérifie et recommence."
    return render_template("connexion.html", erreur=erreur, inscriptions=inscriptions_ouvertes())


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if not inscriptions_ouvertes():
        return render_template("erreur.html", message="Les inscriptions sont fermées. Demande à ton animateur de créer ton compte.")
    classes = toutes_classes()
    erreur, valeurs = None, {}
    if request.method == "POST":
        prenom = re.sub(r"\s+", " ", request.form.get("prenom", "")).strip()[:40]
        code = request.form.get("code", "").strip()
        code2 = request.form.get("code2", "").strip()
        niveau = request.form.get("niveau", "")
        classe = request.form.get("classe", "")
        valeurs = {"prenom": prenom, "niveau": niveau, "classe": classe}
        ids_classes = [str(c["id"]) for c in classes]
        if len(prenom) < 2:
            erreur = "Écris ton prénom."
        elif not re.fullmatch(r"\d{4}", code):
            erreur = "Ton code secret doit avoir exactement 4 chiffres."
        elif code != code2:
            erreur = "Les deux codes ne sont pas pareils. Recommence."
        elif classes and classe not in ids_classes:
            erreur = "Choisis ta classe (ton animateur)."
        elif niveau not in ("1", "2"):
            erreur = "Choisis ton niveau."
        elif db().execute("SELECT 1 FROM eleves WHERE lower(prenom)=? AND code=?", (prenom.lower(), code)).fetchone():
            erreur = "Un élève a déjà ce prénom avec ce code. Choisis un autre code."
        else:
            ident = nouvel_identifiant(prenom)
            classe_id = int(classe) if classes else None
            cur = db().execute("INSERT INTO eleves (prenom, identifiant, code, niveau, cree, classe_id) VALUES (?,?,?,?,?,?)",
                               (prenom, ident, code, int(niveau), maintenant(), classe_id))
            db().commit()
            session.clear()
            session.permanent = True
            session["eleve_id"] = cur.lastrowid
            noter(cur.lastrowid, "inscription", f"Niveau {niveau} · identifiant {ident}")
            return redirect(url_for("bienvenue"))
    return render_template("inscription.html", erreur=erreur, v=valeurs, classes=classes)


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
    return render_template("bienvenue.html", eleve=e, prof=p)


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
                return redirect(url_for("tableau"))
        elif ident == ADMIN:
            if check_password_hash(hache, mdp):
                session.clear()
                session.permanent = True
                session["role"] = "admin"
                return redirect(url_for("tableau"))
            erreur = "Identifiant ou mot de passe incorrect."
        else:
            p = db().execute("SELECT * FROM profs WHERE identifiant=?", (ident,)).fetchone()
            if p and check_password_hash(p["mdp"], mdp):
                session.clear()
                session.permanent = True
                session["role"] = "prof"
                session["prof_id"] = p["id"]
                return redirect(url_for("tableau"))
            erreur = "Identifiant ou mot de passe incorrect."
    return render_template("animateur_connexion.html", premier=not hache, erreur=erreur)


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
                flash(f"Animateur « {nom} » créé (identifiant : {ident}). Sa classe a reçu {n} devoir(s) : le niveau 1 et le niveau 2.")
        elif action == "mdp":
            mdp = request.form.get("mot_de_passe", "")
            if len(mdp) < 6:
                flash("Le mot de passe doit avoir au moins 6 caractères.")
            else:
                db().execute("UPDATE profs SET mdp=? WHERE id=?", (generate_password_hash(mdp), request.form["prof"]))
                db().commit()
                flash("Mot de passe de l'animateur changé.")
        elif action == "supprimer":
            pid = int(request.form["prof"])
            if db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id=?", (pid,)).fetchone()[0]:
                flash("Cette classe a encore des élèves : déplacez-les ou supprimez-les d'abord.")
            else:
                for d in db().execute("SELECT id FROM devoirs WHERE classe_id=?", (pid,)).fetchall():
                    db().execute("DELETE FROM reponses WHERE devoir_id=?", (d["id"],))
                db().execute("DELETE FROM devoirs WHERE classe_id=?", (pid,))
                db().execute("DELETE FROM profs WHERE id=?", (pid,))
                db().commit()
                flash("Animateur et classe supprimés.")
        return redirect(url_for("profs"))
    liste = []
    for p in toutes_classes():
        liste.append({"p": p, "eleves": db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id=?", (p["id"],)).fetchone()[0],
                      "devoirs": db().execute("SELECT COUNT(*) FROM devoirs WHERE classe_id=?", (p["id"],)).fetchone()[0]})
    sans = db().execute("SELECT COUNT(*) FROM eleves WHERE classe_id IS NULL").fetchone()[0]
    return render_template("profs.html", profs=liste, sans_classe=sans)


# ------------------------------------------------------------------ élèves (animateur)
@app.route("/animateur/eleves", methods=["GET", "POST"])
@animateur_requis
def eleves():
    if request.method == "POST":
        niveau = int(request.form.get("niveau", "1"))
        if est_admin():
            c = request.form.get("classe", "")
            classe_id = int(c) if c.isdigit() else None
        else:
            classe_id = session["prof_id"]
        n = 0
        for ligne in request.form.get("prenoms", "").splitlines():
            prenom = ligne.strip()[:40]
            if prenom:
                db().execute("INSERT INTO eleves (prenom, identifiant, code, niveau, cree, classe_id) VALUES (?,?,?,?,?,?)",
                             (prenom, nouvel_identifiant(prenom), nouveau_code(), niveau, maintenant(), classe_id))
                n += 1
        db().commit()
        if n:
            flash(f"{n} élève(s) ajouté(s). Leurs identifiants et codes sont dans la liste.")
        return redirect(url_for("eleves", **args_classe()))
    liste = [e for e in db().execute("SELECT * FROM eleves ORDER BY classe_id, niveau, prenom") if visible(e["classe_id"])]
    return render_template("eleves.html", eleves=liste, noms=nom_classes())


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
        elif action == "classe" and est_admin():
            c = request.form.get("classe", "")
            db().execute("UPDATE eleves SET classe_id=? WHERE id=?", (int(c) if c.isdigit() else None, eid))
            flash("Classe changée.")
        elif action == "code":
            db().execute("UPDATE eleves SET code=? WHERE id=?", (nouveau_code(), eid))
            flash("Nouveau code créé.")
        elif action == "reset":
            db().execute("DELETE FROM reponses WHERE eleve_id=? AND devoir_id=?", (eid, request.form["devoir"]))
            flash("Le devoir est remis à zéro pour cet élève.")
        elif action == "supprimer":
            db().execute("DELETE FROM reponses WHERE eleve_id=?", (eid,))
            db().execute("DELETE FROM journal WHERE eleve_id=?", (eid,))
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
    return render_template("eleve_detail.html", e=e, resultats=resultats, connexions=connexions, prof=prof)


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
    return render_template("mot_de_passe.html")


@app.route("/animateur/deconnexion")
def animateur_deconnexion():
    session.clear()
    return redirect(url_for("animateur_connexion"))


@app.errorhandler(404)
def introuvable(e):
    return render_template("erreur.html", message="Cette page n'existe pas."), 404


@app.errorhandler(403)
def interdit(e):
    return render_template("erreur.html", message="Cette page est réservée à l'administrateur."), 403


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
