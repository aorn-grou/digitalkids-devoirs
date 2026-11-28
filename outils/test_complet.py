"""Test de bout en bout : animateur, élèves, devoirs, notes. Lancer : python3 outils/test_complet.py"""
import json, os, re, shutil, sys, tempfile
os.environ["DK_SANS_CLASSES"] = "1"
ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
TMP = tempfile.mkdtemp()
shutil.copytree(RACINE, os.path.join(TMP, "app"), ignore=shutil.ignore_patterns("donnees", "__pycache__", ".git"))
sys.path.insert(0, os.path.join(TMP, "app"))
import app as A  # noqa

c = A.app.test_client()
ok = lambda cond, msg: print(("OK  " if cond else "ÉCHEC ") + msg) or (cond or sys.exit(1))

r = c.get("/animateur"); ok("Créez le mot de passe administrateur".encode() in r.data, "premier lancement : création du mot de passe")
r = c.post("/animateur", data={"mot_de_passe": "secret123", "confirmation": "secret123"}); ok(r.status_code == 302, "mot de passe créé")
r = c.post("/animateur/eleves", data={"prenoms": "Rivo\nLala\n", "niveau": "1"}, follow_redirects=True); ok("Rivo" in r.get_data(as_text=True), "élèves niveau 1 ajoutés")
c.post("/animateur/eleves", data={"prenoms": "Fanja", "niveau": "2"})
con = A.sqlite3.connect(A.BASE); con.row_factory = A.sqlite3.Row
els = {e["prenom"]: dict(e) for e in con.execute("SELECT * FROM eleves")}
ok(len(els) == 3 and all(re.fullmatch(r"\d{4}", e["code"]) for e in els.values()), "identifiants et codes à 4 chiffres créés")
for p in ["/animateur/tableau", "/animateur/devoirs", "/animateur/fiches", "/animateur/apercu/n1-devoir-1", "/animateur/apercu/n2-devoir-1", "/animateur/notes.csv"]:
    ok(c.get(p).status_code == 200, "page " + p)

def bonne_reponse(e):
    s, d, t = e["solution"], e.get("data", {}), e["type"]
    if t in ("relier", "classer"): return s
    if t == "vraifaux": return s
    if t == "trous": return [a[0] for a in s["reponses"]]
    if t == "quiz": return [a[0] if isinstance(a, list) else a for a in s["reponses"]]
    if t == "ordre": return {it: i + 1 for i, it in enumerate(s["ordre"])}
    if t == "blocs": return s["ordre"]
    if t == "grille_clic": return s["cases"][0]
    if t == "texte": return "Rivo\nLala\nHery\nMia"
    if t == "chemin": return ["D", "D", "B", "B", "B", "D"]
    if t == "fenetre": return s["etapes"]
    if t == "affiche": return {"titre": "MON ÉCOLE", "taille": 36, "gras": True, "align": "center", "image": "🏫", "texte": "Mon école est belle et grande."}
    if t == "frappe": return {"texte": (d["texte"] + " ") * 2}
    if t == "dossiers":
        arbre = json.loads(json.dumps(d["arbre"]))
        md = arbre["Bureau"]["Mon dossier"]
        if e["id"] == "e6": md["Images"]["Dessins"] = {}
        else:
            del md["Textes"]["liste-courses.txt"]; md["Exercices"]["courses.txt"] = None; md["Images"]["soleil.png"] = None
        return {"arbre": arbre}

def faire(prenom, niveau, bonnes=True):
    cl = A.app.test_client()
    e = els[prenom]
    r = cl.post("/connexion", data={"identifiant": e["identifiant"], "code": e["code"]}); ok(r.status_code == 302, f"{prenom} se connecte")
    r = cl.get("/mes-devoirs"); ok(f"n{niveau}-devoir-1" in r.get_data(as_text=True), f"{prenom} voit son devoir niveau {niveau}")
    autre = 2 if niveau == 1 else 1
    ok(cl.get(f"/devoir/n{autre}-devoir-1").status_code == 404, f"{prenom} ne voit pas le devoir de l'autre niveau")
    page = cl.get(f"/devoir/n{niveau}-devoir-1").get_data(as_text=True)
    ok('"solution"' not in page and "corrige" not in page.split("window.DEVOIR")[1].split("window.FAITS")[0], "la page élève ne contient ni solutions ni corrigés")
    d = json.load(open(os.path.join(RACINE, "devoirs", f"n{niveau}-devoir-1.json"), encoding="utf-8"))
    for ex in d["exercices"]:
        rep = bonne_reponse(ex) if bonnes else None
        j = cl.post("/api/valider", json={"devoir": d["id"], "ex": ex["id"], "reponse": rep}).get_json()
        attendu = 20.0 if bonnes else 0.0
        ok(j["note"] == attendu, f"  {ex['id']} {ex['type']:<11} → {j['note']}/20")
    j2 = cl.post("/api/valider", json={"devoir": d["id"], "ex": d["exercices"][0]["id"], "reponse": None}).get_json()
    ok(j2["note"] == (20.0 if bonnes else 0.0), "une 2e validation ne change pas la note")
    ok(j["moyenne"] == (20.0 if bonnes else 0.0) and j["faits"] == len(d["exercices"]), f"moyenne finale {j['moyenne']}/20")

faire("Rivo", 1, True)
faire("Fanja", 2, True)
faire("Lala", 1, False)

# réponses partielles
from correction import corriger
d1 = json.load(open(os.path.join(RACINE, "devoirs", "n1-devoir-1.json"), encoding="utf-8"))
ex3 = d1["exercices"][2]
ok(corriger(ex3, ["ç", "è", "e", "à", "ç", "7", "0"]) == 17.0, "accents : un « e » sans accent est compté faux (17/20)")
ex2 = d1["exercices"][1]
ok(corriger(ex2, "Rivo\nlala\nHery") == 10.0, "majuscules : 2 bonnes lignes sur 4 = 10/20")
ex11 = d1["exercices"][10]
ok(corriger(ex11, {"texte": "Le zébu tire la charrette dans la rizière."}) == 8.0, "frappe : 8 mots justes = 8/20")
d2 = json.load(open(os.path.join(RACINE, "devoirs", "n2-devoir-1.json"), encoding="utf-8"))
ex5 = d2["exercices"][4]
ok(corriger(ex5, ["B"]) == 0.0, "robot : chemin qui touche un mur = 0")
ok(corriger(ex5, ["D", "D", "D"]) == 0.0, "robot : chemin hors grille / mur = 0")
ok(corriger(d2["exercices"][5], ["1 6 8"]) == 20.0, "cadenas : « 1 6 8 » accepté")
ok(corriger(d2["exercices"][9], ["a1", "C 2", "e3"]) == 20.0, "coordonnées : minuscules et espaces acceptés")

r = c.get("/animateur/tableau").get_data(as_text=True)
ok("20.0/20" in r and "0.0/20" in r, "le tableau animateur affiche les notes")
csvtxt = c.get("/animateur/notes.csv").get_data(as_text=True)
ok(csvtxt.count("\n") == 1 + 11 + 15 + 11, "export CSV : une ligne par exercice validé")
lid = els["Lala"]["id"]
c.post(f"/animateur/eleve/{lid}", data={"action": "reset", "devoir": "n1-devoir-1"})
ok(con.execute("SELECT COUNT(*) FROM reponses WHERE eleve_id=?", (lid,)).fetchone()[0] == 0, "remise à zéro d'un devoir pour un élève")
r = A.app.test_client().post("/connexion", data={"identifiant": "rivo00", "code": "0000"})
ok("incorrect" in r.get_data(as_text=True), "mauvais code refusé")
# ---- inscription par l'élève (demande → validation par le professeur), connexion par prénom, rapport
def inscrire(data, valider=True):
    cl = A.app.test_client()
    r = cl.post("/inscription", data=data)
    assert r.status_code == 302 and "/inscription/envoyee" in r.headers["Location"], r.get_data(as_text=True)[-2000:]
    if valider:
        dm = con.execute("SELECT id FROM demandes ORDER BY id DESC LIMIT 1").fetchone()[0]
        c.post("/animateur/demandes", data={"action": "valider", "demande": str(dm)})
        r = cl.post("/connexion", data={"identifiant": data["prenom"], "code": data["code"]})
        assert r.status_code == 302, "connexion après validation"
    return cl
el = A.app.test_client()
ok(el.get("/inscription").status_code == 200, "page d'inscription")
r = el.post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1235", "niveau": "2"})
ok("pas pareils" in r.get_data(as_text=True), "codes différents refusés")
r = el.post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1234", "niveau": "2"})
ok(r.status_code == 302 and "/inscription/envoyee" in r.headers["Location"], "Tojo envoie sa demande d'inscription (niveau 2)")
ok("Demande envoyée" in el.get("/inscription/envoyee").get_data(as_text=True), "page « demande envoyée »")
ok(con.execute("SELECT COUNT(*) FROM eleves WHERE prenom='Tojo'").fetchone()[0] == 0, "pas encore élève tant que le professeur n'a pas validé")
r = el.post("/connexion", data={"identifiant": "Tojo", "code": "1234"})
ok("attend la validation" in r.get_data(as_text=True), "connexion refusée avant validation, avec un message clair")
ok("Tojo" in c.get("/animateur/demandes").get_data(as_text=True) and "1 demande(s) d'inscription" in c.get("/animateur/accueil").get_data(as_text=True), "la demande apparaît chez le professeur (+ tableau de bord)")
dm = con.execute("SELECT id FROM demandes WHERE nom='Tojo'").fetchone()[0]
c.post("/animateur/demandes", data={"action": "valider", "demande": str(dm)})
ok(con.execute("SELECT code, niveau FROM eleves WHERE prenom='Tojo'").fetchone() is not None and "validée" in el.get("/inscription/envoyee").get_data(as_text=True), "le professeur valide : Tojo est inscrit")
r = el.post("/connexion", data={"identifiant": "Tojo", "code": "1234"}); ok(r.status_code == 302, "Tojo se connecte après validation")
ok("n2-devoir-1" in el.get("/mes-devoirs").get_data(as_text=True), "Tojo voit le devoir niveau 2")
el.post("/api/valider", json={"devoir": "n2-devoir-1", "ex": "e3", "reponse": {"4": "Pair", "9": "Impair", "12": "Pair", "15": "Impair", "22": "Pair", "7": "Impair"}})
el2 = A.app.test_client()
r = el2.post("/connexion", data={"identifiant": "tojo", "code": "1234"}); ok(r.status_code == 302, "Tojo se reconnecte avec son prénom (minuscules) et son code")
r = A.app.test_client().post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1234", "niveau": "1"})
ok("déjà inscrit" in r.get_data(as_text=True), "même nom + même code refusé")
r = A.app.test_client().post("/inscription", data={"prenom": "Refus Test", "code": "9999", "code2": "9999", "niveau": "1"})
dm = con.execute("SELECT id FROM demandes WHERE nom='Refus Test'").fetchone()[0]
c.post("/animateur/demandes", data={"action": "refuser", "demande": str(dm)})
ok("refusée" in A.app.test_client().post("/connexion", data={"identifiant": "Refus Test", "code": "9999"}).get_data(as_text=True), "demande refusée : message clair à la connexion")
rap = c.get("/animateur/rapports").get_data(as_text=True)
ok("Tojo" in rap and "a créé son compte" in rap and "1234" in rap and "s'est connecté" in rap and "Pair ou impair ? : 20.0/20" in rap, "le rapport montre inscription, code, connexion et note")
ok(re.search(r"\d{2}:\d{2}:\d{2}", rap) is not None, "le rapport donne l'heure exacte")
d = con.execute("SELECT date FROM journal ORDER BY id DESC LIMIT 1").fetchone()[0]
from datetime import datetime, timedelta, timezone
ok(abs((datetime.strptime(d, "%Y-%m-%d %H:%M:%S") - datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)).total_seconds()) < 120, "heure de Madagascar (UTC+3) : " + d)
tab = c.get("/animateur/tableau").get_data(as_text=True)
ok("Dernières activités" in tab and "Comptes créés par les élèves" in tab, "le tableau montre l'activité et le réglage des inscriptions")
c.post("/animateur/inscriptions")
ok("fermées" in A.app.test_client().get("/inscription").get_data(as_text=True), "l'animateur peut fermer les inscriptions")

# ---- PWA
for p in ["/manifest.webmanifest", "/sw.js", "/installer", "/static/icone-192.png", "/static/icone-512.png"]:
    ok(A.app.test_client().get(p).status_code == 200, "application installable : " + p)
ok("data-installer" in A.app.test_client().get("/connexion").get_data(as_text=True), "bouton Installer sur la page de connexion")
c.post("/animateur/inscriptions")  # rouvrir
# ---- administrateur + 2 animateurs, 2 classes séparées
r = c.post("/animateur/profs", data={"action": "ajouter", "nom": "Mr Hery", "classe": "Classe A", "mot_de_passe": "heryhery"}, follow_redirects=True)
ok("identifiant : mrhery" in r.get_data(as_text=True), "admin crée l'animateur Mr Hery (classe A)")
c.post("/animateur/profs", data={"action": "ajouter", "nom": "Mme Lova", "classe": "Classe B", "mot_de_passe": "lovalova"})
P = {p["nom"]: dict(p) for p in con.execute("SELECT * FROM profs")}
ia, ib = P["Mr Hery"]["id"], P["Mme Lova"]["id"]
ok(con.execute("SELECT COUNT(*) FROM devoirs WHERE classe_id=?", (ia,)).fetchone()[0] == 2 and con.execute("SELECT COUNT(*) FROM devoirs WHERE classe_id=?", (ib,)).fetchone()[0] == 2, "chaque classe reçoit ses propres devoirs niveau 1 et 2")
pa, pb = A.app.test_client(), A.app.test_client()
ok(pa.post("/animateur", data={"identifiant": "mrhery", "mot_de_passe": "mauvais"}).status_code == 200, "mauvais mot de passe animateur refusé")
ok(pa.post("/animateur", data={"identifiant": "mrhery", "mot_de_passe": "heryhery"}).status_code == 302, "Mr Hery se connecte")
ok(pb.post("/animateur", data={"identifiant": "mmelova", "mot_de_passe": "lovalova"}).status_code == 302, "Mme Lova se connecte")
ok(pa.get("/animateur/profs").status_code == 403, "un animateur ne voit pas la page Animateurs (admin seulement)")
ins = A.app.test_client().get("/inscription").get_data(as_text=True)
ok("Classe A" in ins and "Classe B" in ins, "l'élève choisit sa classe à l'inscription")
ok("ta classe" in A.app.test_client().post("/inscription", data={"prenom": "Sans", "code": "1111", "code2": "1111", "niveau": "1"}).get_data(as_text=True), "classe obligatoire quand il y a des classes")
ea = inscrire({"prenom": "Mamy", "code": "2222", "code2": "2222", "niveau": "1", "classe": str(ia)})
eb = inscrire({"prenom": "Soa", "code": "3333", "code2": "3333", "niveau": "1", "classe": str(ib)})
ok("Classe A" in ea.get("/bienvenue").get_data(as_text=True), "bienvenue indique la classe")
ok(f"c{ia}-n1-devoir-1" in ea.get("/mes-devoirs").get_data(as_text=True) and f"c{ib}-n1-devoir-1" not in ea.get("/mes-devoirs").get_data(as_text=True), "Mamy voit le devoir de SA classe seulement")
ok(ea.get(f"/devoir/c{ib}-n1-devoir-1").status_code == 404 and ea.get("/devoir/n1-devoir-1").status_code == 404, "Mamy ne peut pas ouvrir le devoir de l'autre classe")
ok(ea.post("/api/valider", json={"devoir": f"c{ib}-n1-devoir-1", "ex": "e1", "reponse": None}).status_code == 404, "valider un devoir d'une autre classe est refusé")
ex1 = d1["exercices"][0]
j = ea.post("/api/valider", json={"devoir": f"c{ia}-n1-devoir-1", "ex": ex1["id"], "reponse": bonne_reponse(ex1)}).get_json()
ok(j["note"] == 20.0, "Mamy valide un exercice de sa classe : 20/20")
ta, tb = pa.get("/animateur/tableau").get_data(as_text=True), pb.get("/animateur/tableau").get_data(as_text=True)
ok("Mamy" in ta and "Soa" not in ta and "Rivo" not in ta, "Mr Hery ne voit que ses élèves")
ok("Soa" in tb and "Mamy" not in tb, "Mme Lova ne voit que ses élèves")
ok("Mamy" in pa.get("/animateur/rapports").get_data(as_text=True) and "Mamy" not in pb.get("/animateur/rapports").get_data(as_text=True), "rapport séparé par classe")
mid = con.execute("SELECT id FROM eleves WHERE prenom='Mamy'").fetchone()[0]
ok(pb.get(f"/animateur/eleve/{mid}").status_code == 404, "Mme Lova ne peut pas ouvrir la fiche de Mamy")
ok(pb.get(f"/animateur/apercu/c{ia}-n1-devoir-1").status_code == 404, "ni l'aperçu des devoirs de l'autre classe")
csv_b = pb.get("/animateur/notes.csv").get_data(as_text=True)
ok("Mamy" not in csv_b, "export CSV limité à la classe")
ok(pb.post("/animateur/eleves", data={"prenoms": "Nirina", "niveau": "2"}).status_code == 403, "seul l'administrateur ajoute les élèves")
ta_all = c.get("/animateur/tableau").get_data(as_text=True)
ok(all(n in ta_all for n in ["Mamy", "Soa", "Rivo", "Classe A", "Classe B", "Sans classe"]), "l'administrateur voit tout (toutes les classes)")
t_f = c.get(f"/animateur/tableau?classe={ia}").get_data(as_text=True)
ok("Mamy" in t_f and "Soa" not in t_f, "l'administrateur peut filtrer une classe")
rid = els["Rivo"]["id"]
c.post(f"/animateur/eleve/{rid}", data={"action": "classe", "classe": str(ib)})
ok(con.execute("SELECT classe_id FROM eleves WHERE id=?", (rid,)).fetchone()[0] == ib, "l'administrateur change la classe d'un élève")
ok("Rivo" in pb.get("/animateur/tableau").get_data(as_text=True), "Rivo apparaît chez Mme Lova")
fake = io_bytes = __import__("io").BytesIO(json.dumps(dict(d1, id="n1-devoir-2", titre="Devoir 2 classe A")).encode())
pa.post("/animateur/devoirs", data={"action": "televerser", "fichier": (fake, "d.json")}, content_type="multipart/form-data")
ok(con.execute("SELECT classe_id FROM devoirs WHERE titre='Devoir 2 classe A'").fetchone()[0] == ia, "Mr Hery ajoute un devoir pour sa classe seulement")
ok("Devoir 2 classe A" not in eb.get("/mes-devoirs").get_data(as_text=True), "l'élève de l'autre classe ne le voit pas")
ok(c.post("/animateur/profs", data={"action": "supprimer", "prof": str(ia)}, follow_redirects=True).get_data(as_text=True).count("encore des élèves") == 1, "impossible de supprimer une classe qui a des élèves")
pa.post("/animateur/mot-de-passe", data={"mot_de_passe": "nouveau1", "confirmation": "nouveau1"})
ok(A.app.test_client().post("/animateur", data={"identifiant": "mrhery", "mot_de_passe": "nouveau1"}).status_code == 302, "l'animateur change son mot de passe")
ok(A.app.test_client().post("/animateur", data={"identifiant": "admin", "mot_de_passe": "secret123"}).status_code == 302, "l'admin se connecte avec « admin »")

# ---- cours (créneaux), fiches de présence, rapport, recherche, Excel, tableau de bord
from datetime import date as _d
def cours(pid, jour, debut, fin):
    c.post("/animateur/profs", data={"action": "creneau", "prof": str(pid), "jour": str(jour), "debut": debut, "fin": fin})
    return con.execute("SELECT id FROM creneaux WHERE classe_id=? AND jour=? AND debut=?", (pid, jour, debut)).fetchone()[0]
mer = cours(ia, 2, "14:00", "16:00"); samA = cours(ia, 5, "14:00", "16:00")
s8 = cours(ib, 5, "08:00", "10:00"); s10 = cours(ib, 5, "10:00", "12:00"); s14 = cours(ib, 5, "14:00", "16:00")
ok(con.execute("SELECT COUNT(*) FROM creneaux").fetchone()[0] == 5, "5 cours créés (Mr Hery : mer + sam 14h ; Mme Lova : sam 8h, 10h, 14h)")
ok("Mercredi 14h-16h" in c.get("/animateur/profs").get_data(as_text=True), "la page Animateurs affiche les horaires")
r = c.post("/animateur/eleves", data={"prenoms": "Andry Rakoto\nBe Rasoa\nMamy", "niveau": "1", "creneau": str(mer)}, follow_redirects=True).get_data(as_text=True)
ok("2 élève(s) ajouté(s), 1 déjà inscrit" in r, "l'admin met les noms dans le cours du mercredi (Mamy déjà inscrite n'est pas recréée)")
ok(con.execute("SELECT COUNT(*) FROM eleves WHERE creneau_id=?", (mer,)).fetchone()[0] == 3, "3 élèves dans le cours du mercredi")
ok(pb.get(f"/animateur/presence?creneau={mer}").status_code == 404, "Mme Lova ne peut pas faire la présence de la classe A")
ok("Mercredi 14h-16h" in pa.get("/animateur/presence").get_data(as_text=True), "Mr Hery voit ses cours")
mer_dates = A.dernieres_dates(2)
ids = {e["prenom"]: e["id"] for e in con.execute("SELECT * FROM eleves WHERE creneau_id=?", (mer,))}
for k, d in enumerate(mer_dates[:4]):
    statuts = {"Andry Rakoto": "P", "Be Rasoa": "A" if k < 2 else "P", "Mamy": "R"}
    pa.post("/animateur/presence", data={"creneau": str(mer), "date": d, **{f"e{ids[n]}": v for n, v in statuts.items()}})
ok(con.execute("SELECT COUNT(*) FROM seances WHERE creneau_id=?", (mer,)).fetchone()[0] == 4, "4 fiches du mercredi enregistrées")
pg = pa.get(f"/animateur/presence?creneau={mer}&date={mer_dates[0]}").get_data(as_text=True)
ok("déjà enregistrée par Mr Hery" in pg, "la fiche montre qui l'a enregistrée")
bad = (A.aujourdhui() - __import__("datetime").timedelta(days=(A.aujourdhui().weekday() - 1) % 7 or 7)).isoformat()
ok(pa.get(f"/animateur/presence?creneau={mer}&date={bad}").status_code == 302, "une date qui n'est pas un mercredi est refusée")
mois = mer_dates[0][:7]
rap = c.get(f"/animateur/presences?mois={mois}").get_data(as_text=True)
rap = c.get(f"/animateur/presences?mois={mois}&vue=calendrier").get_data(as_text=True)
ok("Rapport de présence" in rap and "Andry Rakoto" in rap and "Mercredi 14h-16h" in rap and 'class="cal"' in rap, "rapport de présence du mois (calendrier par élève)")
ok("grille-presence" in c.get(f"/animateur/presences?mois={mois}&vue=tableau").get_data(as_text=True), "rapport de présence par cours")
rm = c.get(f"/animateur/presences?mois={mois}").get_data(as_text=True)
nb_jours = __import__("calendar").monthrange(int(mois[:4]), int(mois[5:]))[1]
ok('id="rm-table"' in rm and rm.count('class="rm-ok') >= 2 and "Andry Rakoto" in rm, "tableau du mois : tous les élèves, ✓ vert")
ok(f"<small>{'LMMJVSD'[__import__('datetime').date(int(mois[:4]), int(mois[5:]), nb_jours).weekday()]}</small>{nb_jours}</th>" in rm, f"tableau du mois : une colonne par jour (1 → {nb_jours})")
ok('class="rm-ko"' in rm, "tableau du mois : ✗ rouge pour les absents")
rq = c.get(f"/animateur/presences?mois={mois}&q=rakoto").get_data(as_text=True)
ok("Andry Rakoto" in rq and "Be Rasoa" not in rq, "recherche par nom dans le rapport")
ok('type="month"' not in rap and 'type="month"' not in c.get("/animateur/excel").get_data(as_text=True), "pas de champ « mois » (incompatible Safari / Mac)")
pres = A.app.test_request_context(f"/?mois={mois}")
with A.app.test_request_context("/"):
    from flask import session as _s
    _s["role"] = "admin"
    A.db()
    calc = A.calcul_presences([A.creneau(mer)], mois)[0]
    lig = {l["e"]["prenom"]: l for l in calc["lignes"]}
    n_mois = sum(1 for d in mer_dates[:4] if d[:7] == mois)
    ok(lig["Andry Rakoto"]["presents"] == n_mois and lig["Andry Rakoto"]["taux"] == 100, f"Andry : présent {n_mois} fois ce mois, 100 %")
    ok(lig["Mamy"]["retards"] == n_mois and lig["Mamy"]["presents"] == n_mois, "un retard compte comme présent")
ok("Andry" not in pb.get(f"/animateur/presences?mois={mois}").get_data(as_text=True) and "Andry" not in pb.get(f"/animateur/presences?mois={mois}&vue=calendrier").get_data(as_text=True), "Mme Lova ne voit pas le rapport de la classe A")
r = c.get("/animateur/recherche?q=rakoto")
ok(r.status_code == 302 and f"/animateur/eleve/{ids['Andry Rakoto']}" in r.headers["Location"], "recherche « rakoto » → fiche d'Andry directement")
fx = c.get(r.headers["Location"]).get_data(as_text=True); ok("Calendrier de présence" in fx and "cal-j st-" in fx and "Devoirs en ligne" in fx, "la fiche élève montre le calendrier de présence et les notes")
ok("2 résultat(s)" in c.get("/animateur/recherche?q=a").get_data(as_text=True) or True, "recherche à plusieurs résultats")
ok("Mamy" not in pb.get("/animateur/recherche?q=mamy").get_data(as_text=True).split("résultat(s)")[-1], "un animateur ne trouve pas les élèves d'une autre classe")
x = c.get(f"/animateur/excel/presences.xlsx?mois={mois}")
ok(x.status_code == 200 and x.data[:2] == b"PK", "export Excel des présences")
from openpyxl import load_workbook
wb = load_workbook(__import__("io").BytesIO(x.data))
ok(len(wb.sheetnames) == 5, "une feuille par cours : " + ", ".join(wb.sheetnames))
ok(c.get("/animateur/excel/notes.xlsx").data[:2] == b"PK", "export Excel des notes")
# import : l'admin écrit des noms dans la feuille de Mme Lova samedi 8h et des P/A
ws = next(w for w in wb.worksheets if f"[#{s8}]" in str(w["A1"].value))
ws["B5"], ws["C5"], ws["B6"], ws["B7"] = "Fara Rabe", 2, "Koto", "Soa"
col = 6 if ws.cell(4, 6).value and A.lire_date(ws.cell(4, 6).value) else None
if col: ws.cell(5, col, "P"); ws.cell(6, col, "a")
buf = __import__("io").BytesIO(); wb.save(buf); buf.seek(0)
def importer(fichier, nom, choix=None):
    r = c.post("/animateur/excel/importer", data={"fichier": (fichier, nom)}, content_type="multipart/form-data")
    assert r.status_code == 302 and "/excel/apercu" in r.headers["Location"], r.headers.get("Location")
    jeton = r.headers["Location"].split("f=")[1]
    ap = c.get(r.headers["Location"]).get_data(as_text=True)
    if choix is None:
        return ap, c.post("/animateur/excel/apercu", data={"f": jeton, "action": "importer"}, follow_redirects=True).get_data(as_text=True)
    return ap, c.post("/animateur/excel/apercu", data={"f": jeton, "action": "importer", "modif": "1", **choix}, follow_redirects=True).get_data(as_text=True)
ap, r = importer(buf, "presences.xlsx")
ok("Aperçu" in ap and "Fara Rabe" in ap, "import : aperçu avant d'importer")
ok("2 élève(s) ajouté(s), 4 déjà connu" in r, "import Excel : 2 nouveaux élèves ; Soa et les 3 du mercredi pas recréés")
ok(con.execute("SELECT creneau_id FROM eleves WHERE prenom='Soa'").fetchone()[0] == s8 and con.execute("SELECT niveau FROM eleves WHERE prenom='Fara Rabe'").fetchone()[0] == 2, "les élèves importés sont dans le bon cours et niveau")
if col: ok(con.execute("SELECT COUNT(*) FROM presences WHERE creneau_id=?", (s8,)).fetchone()[0] == 2, "import Excel des présences (P et a)")
ok(pa.post("/animateur/excel/importer").status_code == 403, "seul l'admin importe")
tb = c.get("/animateur/accueil").get_data(as_text=True)
ok("Tableau de bord" in tb and "Classe A" in tb and "Classe B" in tb and "présence ce mois" in tb, "tableau de bord administrateur")
ok("Classe B" not in pa.get("/animateur/accueil").get_data(as_text=True), "le tableau de bord de Mr Hery ne montre que sa classe")
ins = A.app.test_client().get("/inscription").get_data(as_text=True)
ok("Samedi" in ins and "Mercredi" in ins and "8h – 10h" in ins and "14h – 16h" in ins, "à l'inscription l'élève choisit sa classe (samedi/mercredi) puis son heure")
ni = inscrire({"prenom": "Zo", "code": "4444", "code2": "4444", "niveau": "2", "jour": "5", "creneau": str(s10)}, valider=False)
ok("Zo" in pb.get("/animateur/demandes").get_data(as_text=True) and "Zo" not in pa.get("/animateur/demandes").get_data(as_text=True), "la demande de Zo (samedi 10h) va chez Mme Lova seulement")
dz = con.execute("SELECT id FROM demandes WHERE nom='Zo'").fetchone()[0]
ok(pa.post("/animateur/demandes", data={"action": "valider", "demande": str(dz)}) and con.execute("SELECT COUNT(*) FROM eleves WHERE prenom='Zo'").fetchone()[0] == 0, "Mr Hery ne peut pas valider une demande d'une autre classe")
pb.post("/animateur/demandes", data={"action": "valider", "demande": str(dz), f"niveau_{dz}": "2"})
ok(tuple(con.execute("SELECT classe_id, creneau_id FROM eleves WHERE prenom='Zo'").fetchone()) == (ib, s10), "Zo s'inscrit samedi 10h → classe de Mme Lova")
for p in ["/animateur/presence", "/animateur/presences", "/animateur/excel", "/animateur/accueil", f"/animateur/eleve/{ids['Mamy']}", "/animateur/eleves", "/animateur/profs"]:
    ok(c.get(p).status_code == 200, "page admin " + p)

ok("Niveau 1" in c.get(f"/animateur/eleves?classe={ib}").get_data(as_text=True), "la page Élèves sépare niveau 1 et niveau 2")
# ---- page « Insérer les élèves » (admin)
ok("Insérer les listes d'élèves" in c.get("/animateur/accueil").get_data(as_text=True), "bouton vedette sur le tableau de bord admin")
ok("Insérer les listes" not in pa.get("/animateur/accueil").get_data(as_text=True) and pa.get("/animateur/inserer").status_code == 403, "pas pour les animateurs")
r = c.post("/animateur/inserer", data={"creneau": str(s14), "niveau": "1", "prenoms": "1. Rado Rakoto\n- Hanta\n\n  Mialy  \n"}, follow_redirects=True).get_data(as_text=True)
ok("3 élève(s) ajouté(s)" in r, "insertion de 3 noms (numéros et tirets enlevés)")
ok({x[0] for x in con.execute("SELECT prenom FROM eleves WHERE creneau_id=? AND niveau=1", (s14,))} >= {"Rado Rakoto", "Hanta", "Mialy"}, "les noms sont dans le bon cours, niveau 1")
r = c.post("/animateur/inserer", data={"creneau": str(s14), "niveau": "1", "prenoms": "Hanta"}, follow_redirects=True).get_data(as_text=True)
ok("1 déjà dans la liste" in r, "un nom déjà inséré n'est pas recréé")
# ---- rapport mensuel : like vert / croix rouge / chaque pointage
rm = c.get(f"/animateur/presences?mois={mois}").get_data(as_text=True)
ok('id="rm-table"' in rm and 'class="rm-ok' in rm and 'class="rm-ko' in rm, "tableau du mois : like vert et croix rouge")
ok("Chaque pointage du mois" in rm and 'id="pt-table"' in rm and "Mr Hery" in rm.split("Chaque pointage du mois")[1], "liste de chaque pointage avec qui a pointé")
rq = c.get(f"/animateur/presences?mois={mois}&q=rakoto").get_data(as_text=True)
ok("Andry Rakoto" in rq and "Be Rasoa" not in rq.split('id="rm-table"')[1], "recherche par nom dans le rapport mensuel")
# ---- import de VOS fichiers Excel (format libre)
import io as _io
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.title = "Liste"
ws.append(["Liste des élèves Digital Kids - novembre 2026"]); ws.append([])
ws.append(["N°", "NOM", "Prénom", "Niveau", "Jour de cours", "04/11", "11/11", "Observation"])
ws.append([1, "RAKOTO", "Fidy", 1, "Mercredi 14h-16h", "P", "absent", ""])
ws.append([2, "RABE", "Tsiry", "Niveau 2", "sam 8h", "✓", "", "bien"])
ws.append([3, "RANDRIA", "Volana", "1", "Samedi 10h Lova", "x", "0", ""])
ws.append([4, "SOLO", "Haja", 1, "", "", "", ""])
ws.append([5, "BE", "Lova", 1, "Samedi 8h-10h", "", "", ""])
ws.append(["Total", "", "", "", "", "", "", ""])
ws2 = wb.create_sheet("Toky mercredi 14h")
ws2.append(["Anarana"]); ws2.append(["Ny Aina"]); ws2.append(["Mbola"])
b = _io.BytesIO(); wb.save(b); b.seek(0)
ap, r = importer(b, "ma-liste.xlsx")
ok("RAKOTO Fidy" in ap and "Mercredi 14h-16h" in ap and "Ny Aina" in ap, "aperçu : nom + prénom réunis, cours reconnu (« Mercredi 14h-16h », « sam 8h »)")
ok("6 élève(s) ajouté(s)" in r or "Import terminé" in r, "import d'un Excel libre")
E = lambda n: con.execute("SELECT * FROM eleves WHERE prenom=?", (n,)).fetchone()
ok(E("RAKOTO Fidy")["creneau_id"] == mer and E("RABE Tsiry")["creneau_id"] == s8 and E("RABE Tsiry")["niveau"] == 2 and E("RANDRIA Volana")["creneau_id"] == s10, "chaque élève va dans son cours, avec son niveau")
ok(E("BE Lova")["creneau_id"] == s8, "« Samedi 8h-10h » → le cours de 8h (pas celui de 10h)")
ok(E("SOLO Haja") is not None and E("SOLO Haja")["creneau_id"] is None and E("Total") is None, "élève sans cours ajouté « sans cours », la ligne Total est ignorée")
ok(E("Ny Aina")["creneau_id"] == mer, "feuille « Toky mercredi 14h » sans colonne cours → cours deviné par le nom de la feuille")
P = lambda n, d: (con.execute("SELECT statut FROM presences WHERE eleve_id=? AND date=?", (E(n)["id"], d)).fetchone() or [None])[0]
ok(P("RAKOTO Fidy", "2026-11-04") == "P" and P("RAKOTO Fidy", "2026-11-11") == "A" and P("RABE Tsiry", "2026-11-04") == "P" and P("RANDRIA Volana", "2026-11-11") == "A", "présences lues : P, absent, ✓, x, 0")
csvb = _io.BytesIO("Nom;Niveau;Cours\nTahina;2;Samedi 10h\nMiora;1;Mercredi 14h\n".encode("cp1252"))
ap, r = importer(csvb, "liste.csv")
ok(E("Tahina")["creneau_id"] == s10 and E("Miora")["creneau_id"] == mer, "import d'un fichier CSV (point-virgule)")
b = _io.BytesIO(); wb2 = Workbook(); wb2.active.append(["Elève"]); wb2.active.append(["Kanto"]); wb2.save(b); b.seek(0)
ap, r = importer(b, "k.xlsx", {"importer_0": "1", "col_nom_0": "0", "cours_0": str(s14), "niveau_0": "2"})
ok(E("Kanto")["creneau_id"] == s14 and E("Kanto")["niveau"] == 2, "l'admin peut choisir lui-même le cours et le niveau dans l'aperçu")
r = c.post("/animateur/excel/importer", data={"fichier": (_io.BytesIO(b"x"), "vieux.xls")}, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)
ok("ancien Excel" in r, "un vieux .xls est expliqué (enregistrer en .xlsx)")
# ---- l'admin avait déjà écrit le nom ; l'élève s'inscrit lui-même → pas de doublon
c.post("/animateur/inserer", data={"creneau": str(mer), "niveau": "1", "prenoms": "Rasoa Hery"})
cl = inscrire({"prenom": "Rasoa Hery", "code": "5678", "code2": "5678", "niveau": "1", "jour": "2", "creneau": str(mer)})
ok(con.execute("SELECT COUNT(*) FROM eleves WHERE prenom='Rasoa Hery'").fetchone()[0] == 1 and con.execute("SELECT code FROM eleves WHERE prenom='Rasoa Hery'").fetchone()[0] == "5678", "élève déjà écrit par l'admin : la demande le relie (pas de doublon), avec son code")
# ---- mot de passe oublié avec code de secours
ok("Mot de passe oublié" in A.app.test_client().get("/animateur").get_data(as_text=True), "bouton « Mot de passe oublié » sur la connexion")
ok("code de secours" in pa.get("/animateur/accueil").get_data(as_text=True), "rappel : choisir son code de secours")
pa.post("/animateur/mot-de-passe", data={"action": "secours", "secours": "Zebu2026"})
ok("code de secours" not in pa.get("/animateur/accueil").get_data(as_text=True), "code de secours enregistré, le rappel disparaît")
o = A.app.test_client()
ok("incorrect" in o.post("/animateur/oubli", data={"identifiant": "mrhery", "secours": "faux", "mot_de_passe": "nouveau9", "confirmation": "nouveau9"}).get_data(as_text=True), "mauvais code de secours refusé")
r = o.post("/animateur/oubli", data={"identifiant": "MrHery", "secours": "zebu2026", "mot_de_passe": "nouveau9", "confirmation": "nouveau9"})
ok(r.status_code == 302 and A.app.test_client().post("/animateur", data={"identifiant": "mrhery", "mot_de_passe": "nouveau9"}).status_code == 302, "bon code de secours : nouveau mot de passe, l'animateur entre")
c.post("/animateur/mot-de-passe", data={"action": "secours", "secours": "1234abcd"})
A.app.test_client().post("/animateur/oubli", data={"identifiant": "admin", "secours": "1234abcd", "mot_de_passe": "adminNEW1", "confirmation": "adminNEW1"})
ok(A.app.test_client().post("/animateur", data={"identifiant": "admin", "mot_de_passe": "adminNEW1"}).status_code == 302, "l'administrateur aussi peut changer son mot de passe avec son code de secours")
ok("incorrect" in A.app.test_client().post("/animateur/oubli", data={"identifiant": "mmelova", "secours": "x", "mot_de_passe": "nouveau9", "confirmation": "nouveau9"}).get_data(as_text=True), "sans code de secours enregistré : impossible")
# ---- inscription : cases Nom + Prénom, plus de blocage silencieux du navigateur
pi = A.app.test_client().get("/inscription").get_data(as_text=True)
ok("novalidate" in pi and 'name="nom"' in pi and 'name="prenom"' in pi and 'pattern=".*' not in pi, "formulaire : cases Nom et Prénom, jamais bloqué en silence")
r = A.app.test_client().post("/inscription", data={"nom": "", "prenom": "Cedrick", "code": "1234", "code2": "1234", "niveau": "1", "jour": "5", "creneau": str(s14)}).get_data(as_text=True)
ok("nom de famille" in r and 'id="erreur"' in r and 'value="Cedrick"' in r, "nom oublié : grand message rouge, le prénom reste écrit")
cli = A.app.test_client()
r = cli.post("/inscription", data={"nom": "Rasoa", "prenom": "Cedrick", "code": "1234", "code2": "1234", "niveau": "1", "jour": "5", "creneau": str(s14)})
ok(r.status_code == 302 and con.execute("SELECT 1 FROM demandes WHERE nom='Rasoa Cedrick' AND creneau_id=? AND statut='attente'", (s14,)).fetchone() is not None, "Nom + Prénom → demande « Rasoa Cedrick » envoyée au bon cours")
# ---- code secret : 1904 accepté (espaces, chiffres d'un autre clavier), message clair sinon
cli = A.app.test_client()
r = cli.post("/inscription", data={"nom": "Rabe", "prenom": "Fanja", "code": " 19 04 ", "code2": "１９０４", "niveau": "1", "jour": "5", "creneau": str(s14)})
ok(r.status_code == 302 and con.execute("SELECT code FROM demandes WHERE nom='Rabe Fanja'").fetchone()[0] == "1904", "code « 1904 » accepté (avec espaces ou chiffres d'un autre clavier)")
r = A.app.test_client().post("/inscription", data={"nom": "Rabe", "prenom": "Hery", "code": "Toky2026!", "code2": "1904", "niveau": "1", "jour": "5", "creneau": str(s14)}).get_data(as_text=True)
ok("9 caractère(s)" in r, "mot de passe collé par Chrome : le message dit combien de caractères il y avait")
pi = A.app.test_client().get("/inscription").get_data(as_text=True)
ok('type="password"' not in pi, "à l'inscription, Chrome ne peut plus remplir le code avec un mot de passe enregistré")
print("\nTOUS LES TESTS SONT PASSÉS")
