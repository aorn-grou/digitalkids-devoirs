"""Digital Kids Anjanahary · Devoirs en ligne
Application Flask : connexion des élèves, devoirs interactifs notés sur 20, espace animateur."""
import csv
import io
import json
import os
import random
import re
import secrets
import sqlite3
import unicodedata
from datetime import datetime
from functools import wraps
from datetime import timedelta, timezone

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   Response, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from correction import CORRECTEURS, corriger

ICI = os.path.dirname(os.path.abspath(__file__))
DONNEES = os.path.join(ICI, "donnees")
DOSSIER_DEVOIRS = os.path.join(ICI, "devoirs")
os.makedirs(DONNEES, exist_ok=True)
BASE = os.path.join(DONNEES, "ecole.db")


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
    """)
    con.commit()
    # premier lancement : on importe les devoirs du dossier devoirs/
    if con.execute("SELECT COUNT(*) FROM devoirs").fetchone()[0] == 0:
        importer_dossier(con)
    con.close()


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


def enregistrer_devoir(con, d):
    con.execute("""INSERT INTO devoirs (id, niveau, titre, semaine, contenu, actif, cree) VALUES (?,?,?,?,?,1,?)
                   ON CONFLICT(id) DO UPDATE SET niveau=excluded.niveau, titre=excluded.titre,
                   semaine=excluded.semaine, contenu=excluded.contenu""",
                (d["id"], int(d["niveau"]), d["titre"], d.get("semaine", ""), json.dumps(d, ensure_ascii=False),
                 maintenant()))


def importer_dossier(con):
    n = 0
    if os.path.isdir(DOSSIER_DEVOIRS):
        for nom in sorted(os.listdir(DOSSIER_DEVOIRS)):
            if nom.endswith(".json"):
                with open(os.path.join(DOSSIER_DEVOIRS, nom), encoding="utf-8") as f:
                    d = json.load(f)
                if verifier_devoir(d) is None:
                    enregistrer_devoir(con, d)
                    n += 1
    con.commit()
    return n


def noter(eleve_id, type_, detail=""):
    """Ajoute une ligne au rapport de l'animateur."""
    db().execute("INSERT INTO journal (date, eleve_id, type, detail) VALUES (?,?,?,?)",
                 (maintenant(), eleve_id, type_, detail))
    db().commit()


def inscriptions_ouvertes():
    return reglage("inscriptions", "1") == "1"


def reglage(cle, defaut=None):
    r = db().execute("SELECT valeur FROM reglages WHERE cle=?", (cle,)).fetchone()
    return r["valeur"] if r else defaut


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
        # on mélange l'ordre des propositions pour relier/classer/ordre/blocs (stable par élève)
        rnd = random.Random(f"{d['id']}-{e['id']}-{session.get('eleve_id')}")
        if e["type"] in ("relier",):
            droite = list(data.get("droite", []))
            rnd.shuffle(droite)
            data = dict(data, droite=droite)
        e["data"] = data
    return c


def moyenne(notes):
    return round(sum(notes) / len(notes), 1) if notes else None


# ------------------------------------------------------------------ outils
def slug(s):
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z]", "", s.lower())[:8] or "eleve"


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
        if not session.get("animateur"):
            return redirect(url_for("animateur_connexion"))
        return f(*a, **k)
    return w


@app.context_processor
def contexte():
    nouveaux = 0
    if session.get("animateur"):
        try:
            nouveaux = db().execute("SELECT COUNT(*) FROM journal WHERE lu=0").fetchone()[0]
        except sqlite3.Error:
            nouveaux = 0
    return {"annee": datetime.now().year, "rapports_nouveaux": nouveaux}


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
            # on accepte l'identifiant (rivo25) ou le prénom (Rivo) avec le bon code
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
                erreur = "Plusieurs élèves ont ce prénom : écris ton identifiant (par exemple rivo25)."
            else:
                session["tentatives"] = tentatives + 1
                erreur = "Prénom ou code incorrect. Vérifie et recommence."
    return render_template("connexion.html", erreur=erreur, inscriptions=inscriptions_ouvertes())


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if not inscriptions_ouvertes():
        return render_template("erreur.html", message="Les inscriptions sont fermées. Demande à ton animateur de créer ton compte.")
    erreur, valeurs = None, {}
    if request.method == "POST":
        prenom = re.sub(r"\s+", " ", request.form.get("prenom", "")).strip()[:40]
        code = request.form.get("code", "").strip()
        code2 = request.form.get("code2", "").strip()
        niveau = request.form.get("niveau", "")
        valeurs = {"prenom": prenom, "niveau": niveau}
        if len(prenom) < 2:
            erreur = "Écris ton prénom."
        elif not re.fullmatch(r"\d{4}", code):
            erreur = "Ton code secret doit avoir exactement 4 chiffres."
        elif code != code2:
            erreur = "Les deux codes ne sont pas pareils. Recommence."
        elif niveau not in ("1", "2", "3"):
            erreur = "Choisis ton niveau."
        elif db().execute("SELECT 1 FROM eleves WHERE lower(prenom)=? AND code=?", (prenom.lower(), code)).fetchone():
            erreur = "Un élève a déjà ce prénom avec ce code. Choisis un autre code."
        else:
            ident = nouvel_identifiant(prenom)
            cur = db().execute("INSERT INTO eleves (prenom, identifiant, code, niveau, cree) VALUES (?,?,?,?,?)",
                               (prenom, ident, code, int(niveau), maintenant()))
            db().commit()
            session.clear()
            session.permanent = True
            session["eleve_id"] = cur.lastrowid
            session["nouveau"] = True
            noter(cur.lastrowid, "inscription", f"Niveau {niveau} · identifiant {ident}")
            return redirect(url_for("bienvenue"))
    return render_template("inscription.html", erreur=erreur, v=valeurs)


@app.route("/bienvenue")
@eleve_requis
def bienvenue():
    return render_template("bienvenue.html", eleve=eleve_courant())


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("connexion"))


def eleve_courant():
    return db().execute("SELECT * FROM eleves WHERE id=?", (session["eleve_id"],)).fetchone()


@app.route("/mes-devoirs")
@eleve_requis
def mes_devoirs():
    e = eleve_courant()
    if not e:
        session.clear()
        return redirect(url_for("connexion"))
    lignes = db().execute("SELECT * FROM devoirs WHERE niveau=? AND actif=1 ORDER BY cree DESC, id DESC", (e["niveau"],)).fetchall()
    devoirs = []
    for r in lignes:
        d = json.loads(r["contenu"])
        notes = [x["note"] for x in db().execute("SELECT note FROM reponses WHERE eleve_id=? AND devoir_id=?", (e["id"], r["id"]))]
        devoirs.append({"id": r["id"], "titre": r["titre"], "semaine": r["semaine"], "total": len(d["exercices"]),
                        "faits": len(notes), "moyenne": moyenne(notes)})
    return render_template("mes_devoirs.html", eleve=e, devoirs=devoirs)


@app.route("/devoir/<devoir_id>")
@eleve_requis
def devoir(devoir_id):
    e = eleve_courant()
    r, d = charger_devoir(devoir_id)
    if not r or not r["actif"] or r["niveau"] != e["niveau"]:
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
    if not r or not r["actif"] or r["niveau"] != e["niveau"]:
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
        db().execute("INSERT INTO reponses VALUES (?,?,?,?,?,?)",
                     (e["id"], r["id"], ex["id"], texte, note, maintenant()))
        db().commit()
    notes = [x["note"] for x in db().execute("SELECT note FROM reponses WHERE eleve_id=? AND devoir_id=?", (e["id"], r["id"]))]
    if not deja:
        noter(e["id"], "exercice", f"{r['titre']} · {ex['titre']} : {note}/20")
        if len(notes) == 1:
            noter(e["id"], "debut", f"{r['titre']}")
        if len(notes) == len(d["exercices"]):
            noter(e["id"], "fini", f"{r['titre']} · moyenne {moyenne(notes)}/20")
    return jsonify(note=note, corrige=ex.get("corrige", ""), faits=len(notes), total=len(d["exercices"]), moyenne=moyenne(notes))


# ------------------------------------------------------------------ animateur
@app.route("/animateur", methods=["GET", "POST"])
def animateur_connexion():
    hache = reglage("mot_de_passe")
    erreur = None
    if request.method == "POST":
        mdp = request.form.get("mot_de_passe", "")
        if not hache:  # premier lancement : on crée le mot de passe
            if len(mdp) < 6 or mdp != request.form.get("confirmation", ""):
                erreur = "Le mot de passe doit avoir au moins 6 caractères, écrit 2 fois pareil."
            else:
                db().execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (generate_password_hash(mdp),))
                db().commit()
                session.clear()
                session["animateur"] = True
                return redirect(url_for("tableau"))
        elif check_password_hash(hache, mdp):
            session.clear()
            session.permanent = True
            session["animateur"] = True
            return redirect(url_for("tableau"))
        else:
            erreur = "Mot de passe incorrect."
    return render_template("animateur_connexion.html", premier=not hache, erreur=erreur)


@app.route("/animateur/tableau")
@animateur_requis
def tableau():
    eleves = db().execute("SELECT * FROM eleves ORDER BY niveau, prenom").fetchall()
    devoirs = db().execute("SELECT id, niveau, titre, semaine, actif, contenu FROM devoirs ORDER BY niveau, cree DESC").fetchall()
    notes = {}
    for x in db().execute("SELECT eleve_id, devoir_id, COUNT(*) n, AVG(note) m FROM reponses GROUP BY eleve_id, devoir_id"):
        notes[(x["eleve_id"], x["devoir_id"])] = (x["n"], round(x["m"], 1))
    nb_ex = {d["id"]: len(json.loads(d["contenu"])["exercices"]) for d in devoirs}
    derniere = {x["eleve_id"]: x["d"] for x in db().execute("SELECT eleve_id, MAX(date) d FROM journal WHERE type IN ('connexion','inscription') GROUP BY eleve_id")}
    recents = db().execute("""SELECT j.*, e.prenom FROM journal j LEFT JOIN eleves e ON e.id = j.eleve_id
                              ORDER BY j.id DESC LIMIT 8""").fetchall()
    return render_template("tableau.html", eleves=eleves, devoirs=devoirs, notes=notes, nb_ex=nb_ex,
                           recents=recents, derniere=derniere, inscriptions=inscriptions_ouvertes())


@app.route("/animateur/eleves", methods=["GET", "POST"])
@animateur_requis
def eleves():
    nouveaux = []
    if request.method == "POST":
        niveau = int(request.form.get("niveau", "1"))
        for ligne in request.form.get("prenoms", "").splitlines():
            prenom = ligne.strip()[:40]
            if not prenom:
                continue
            ident, code = nouvel_identifiant(prenom), nouveau_code()
            db().execute("INSERT INTO eleves (prenom, identifiant, code, niveau, cree) VALUES (?,?,?,?,?)",
                         (prenom, ident, code, niveau, maintenant()))
            nouveaux.append(ident)
        db().commit()
        if nouveaux:
            flash(f"{len(nouveaux)} élève(s) ajouté(s). Leurs identifiants et codes sont dans la liste.")
        return redirect(url_for("eleves"))
    liste = db().execute("SELECT * FROM eleves ORDER BY niveau, prenom").fetchall()
    return render_template("eleves.html", eleves=liste)


@app.route("/animateur/eleve/<int:eid>", methods=["GET", "POST"])
@animateur_requis
def eleve_detail(eid):
    e = db().execute("SELECT * FROM eleves WHERE id=?", (eid,)).fetchone()
    if not e:
        abort(404)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "niveau":
            db().execute("UPDATE eleves SET niveau=? WHERE id=?", (int(request.form["niveau"]), eid))
            flash("Niveau changé.")
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
        d = json.loads(r["contenu"])
        reps = {x["ex_id"]: x for x in db().execute("SELECT * FROM reponses WHERE eleve_id=? AND devoir_id=?", (eid, r["id"]))}
        if not reps and r["niveau"] != e["niveau"]:
            continue
        lignes = [{"titre": x["titre"], "note": reps[x["id"]]["note"] if x["id"] in reps else None,
                   "date": reps[x["id"]]["date"] if x["id"] in reps else ""} for x in d["exercices"]]
        resultats.append({"id": r["id"], "titre": r["titre"], "lignes": lignes,
                          "moyenne": moyenne([l["note"] for l in lignes if l["note"] is not None])})
    return render_template("eleve_detail.html", e=e, resultats=resultats)


@app.route("/animateur/fiches")
@animateur_requis
def fiches():
    liste = db().execute("SELECT * FROM eleves ORDER BY niveau, prenom").fetchall()
    return render_template("fiches.html", eleves=liste, adresse=request.host_url.rstrip("/"))


@app.route("/animateur/devoirs", methods=["GET", "POST"])
@animateur_requis
def devoirs_admin():
    if request.method == "POST":
        action = request.form.get("action")
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
                enregistrer_devoir(db(), d)
                db().commit()
                flash(f"Devoir « {d['titre']} » ajouté pour le niveau {d['niveau']}.")
        elif action == "importer":
            n = importer_dossier(db())
            flash(f"{n} devoir(s) importé(s) depuis le dossier devoirs/.")
        elif action == "actif":
            db().execute("UPDATE devoirs SET actif = 1 - actif WHERE id=?", (request.form["devoir"],))
            db().commit()
        elif action == "supprimer":
            db().execute("DELETE FROM reponses WHERE devoir_id=?", (request.form["devoir"],))
            db().execute("DELETE FROM devoirs WHERE id=?", (request.form["devoir"],))
            db().commit()
            flash("Devoir supprimé.")
        return redirect(url_for("devoirs_admin"))
    liste = []
    for r in db().execute("SELECT * FROM devoirs ORDER BY niveau, cree DESC"):
        d = json.loads(r["contenu"])
        n = db().execute("SELECT COUNT(DISTINCT eleve_id) FROM reponses WHERE devoir_id=?", (r["id"],)).fetchone()[0]
        liste.append({"r": r, "nb": len(d["exercices"]), "eleves": n})
    return render_template("devoirs_admin.html", devoirs=liste)


@app.route("/animateur/rapports")
@animateur_requis
def rapports():
    jour = request.args.get("jour") or maintenant()[:10]
    lignes = db().execute("""SELECT j.*, e.prenom, e.identifiant, e.niveau, e.code FROM journal j LEFT JOIN eleves e ON e.id = j.eleve_id
                             WHERE substr(j.date,1,10)=? ORDER BY j.id DESC""", (jour,)).fetchall()
    # résumé : une ligne par élève actif ce jour-là
    resume = {}
    for l in reversed(lignes):
        if l["eleve_id"] is None or l["prenom"] is None:
            continue
        r = resume.setdefault(l["eleve_id"], {"prenom": l["prenom"], "identifiant": l["identifiant"], "code": l["code"],
                                              "niveau": l["niveau"], "premiere": l["date"], "derniere": l["date"],
                                              "connexions": 0, "exercices": 0, "fini": None, "id": l["eleve_id"]})
        r["derniere"] = l["date"]
        if l["type"] in ("connexion", "inscription"):
            r["connexions"] += 1
        elif l["type"] == "exercice":
            r["exercices"] += 1
        elif l["type"] == "fini":
            r["fini"] = (l["date"], l["detail"])
    jours = [x[0] for x in db().execute("SELECT DISTINCT substr(date,1,10) FROM journal ORDER BY 1 DESC LIMIT 30")]
    page = render_template("rapports.html", lignes=lignes, resume=list(resume.values()), jour=jour, jours=jours)
    db().execute("UPDATE journal SET lu=1 WHERE lu=0")
    db().commit()
    return page


@app.route("/animateur/inscriptions", methods=["POST"])
@animateur_requis
def basculer_inscriptions():
    db().execute("INSERT OR REPLACE INTO reglages VALUES ('inscriptions', ?)", ("0" if inscriptions_ouvertes() else "1",))
    db().commit()
    flash("Inscriptions " + ("ouvertes : les élèves peuvent créer leur compte." if inscriptions_ouvertes() else "fermées."))
    return redirect(url_for("tableau"))


@app.route("/animateur/notes.csv")
@animateur_requis
def notes_csv():
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Prénom", "Identifiant", "Niveau", "Devoir", "Exercice", "Note /20", "Date"])
    for x in db().execute("""SELECT e.prenom, e.identifiant, e.niveau, r.devoir_id, r.ex_id, r.note, r.date
                             FROM reponses r JOIN eleves e ON e.id = r.eleve_id ORDER BY e.niveau, e.prenom, r.devoir_id, r.ex_id"""):
        w.writerow([x["prenom"], x["identifiant"], x["niveau"], x["devoir_id"], x["ex_id"], str(x["note"]).replace(".", ","), x["date"]])
    return Response("﻿" + sortie.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=notes-digital-kids.csv"})


@app.route("/animateur/apercu/<devoir_id>")
@animateur_requis
def apercu(devoir_id):
    r, d = charger_devoir(devoir_id)
    if not r:
        abort(404)
    return render_template("devoir.html", eleve=None, devoir=version_eleve(d), faits={}, apercu=True,
                           corriges={e["id"]: e.get("corrige", "") for e in d["exercices"]})


@app.route("/animateur/mot-de-passe", methods=["GET", "POST"])
@animateur_requis
def mot_de_passe():
    if request.method == "POST":
        mdp = request.form.get("mot_de_passe", "")
        if len(mdp) < 6 or mdp != request.form.get("confirmation", ""):
            flash("Le mot de passe doit avoir au moins 6 caractères, écrit 2 fois pareil.")
        else:
            db().execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (generate_password_hash(mdp),))
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


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
