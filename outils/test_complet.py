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

r = c.get("/animateur"); ok(b"Cr\xc3\xa9ez votre mot de passe" in r.data, "premier lancement : création du mot de passe")
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
print("\nTOUS LES TESTS SONT PASSÉS")
