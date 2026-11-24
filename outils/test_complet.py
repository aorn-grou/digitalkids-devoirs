"""Test de bout en bout : animateur, élèves, devoirs, notes. Lancer : python3 outils/test_complet.py"""
import json, os, re, shutil, sys, tempfile
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
# ---- inscription par l'élève, connexion par prénom, rapport
el = A.app.test_client()
ok(el.get("/inscription").status_code == 200, "page d'inscription")
r = el.post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1235", "niveau": "2"})
ok("pas pareils" in r.get_data(as_text=True), "codes différents refusés")
r = el.post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1234", "niveau": "2"})
ok(r.status_code == 302 and "/bienvenue" in r.headers["Location"], "Tojo crée son compte niveau 2")
ok("Bienvenue Tojo" in el.get("/bienvenue").get_data(as_text=True), "page de bienvenue")
ok("n2-devoir-1" in el.get("/mes-devoirs").get_data(as_text=True), "Tojo voit le devoir niveau 2")
el.post("/api/valider", json={"devoir": "n2-devoir-1", "ex": "e3", "reponse": {"4": "Pair", "9": "Impair", "12": "Pair", "15": "Impair", "22": "Pair", "7": "Impair"}})
el2 = A.app.test_client()
r = el2.post("/connexion", data={"identifiant": "tojo", "code": "1234"}); ok(r.status_code == 302, "Tojo se reconnecte avec son prénom (minuscules) et son code")
r = A.app.test_client().post("/inscription", data={"prenom": "Tojo", "code": "1234", "code2": "1234", "niveau": "1"})
ok("déjà ce prénom" in r.get_data(as_text=True), "même prénom + même code refusé")
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
ea, eb = A.app.test_client(), A.app.test_client()
ea.post("/inscription", data={"prenom": "Mamy", "code": "2222", "code2": "2222", "niveau": "1", "classe": str(ia)})
eb.post("/inscription", data={"prenom": "Soa", "code": "3333", "code2": "3333", "niveau": "1", "classe": str(ib)})
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
pb.post("/animateur/eleves", data={"prenoms": "Nirina", "niveau": "2", "classe": str(ia)})
ok(con.execute("SELECT classe_id FROM eleves WHERE prenom='Nirina'").fetchone()[0] == ib, "un élève ajouté par Mme Lova va dans SA classe")
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
print("\nTOUS LES TESTS SONT PASSÉS")
