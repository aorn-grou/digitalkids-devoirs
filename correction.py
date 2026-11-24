"""Correction automatique des exercices. Chaque fonction renvoie une note sur 20."""
import re
import unicodedata


def sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s, strict=False):
    s = str(s or "").strip().lower()
    if not strict:
        s = sans_accents(s)
    return s


def compact(s):
    """Pour codes, coordonnées, nombres : on enlève espaces, tirets, virgules, points."""
    return re.sub(r"[\s\-–—,.;:/]+", "", norm(s))


def arrondi(x):
    return round(max(0.0, min(20.0, x)) * 2) / 2  # au demi-point


def ratio(bons, total):
    return arrondi(20.0 * bons / total) if total else 0.0


# ------------------------------------------------------------------ types simples
def c_relier(data, sol, rep):
    rep = rep or {}
    bons = sum(1 for g, d in sol.items() if rep.get(g) == d)
    return ratio(bons, len(sol))


def c_classer(data, sol, rep):
    return c_relier(data, sol, rep)


def c_vraifaux(data, sol, rep):
    rep = rep or []
    bons = sum(1 for i, v in enumerate(sol) if i < len(rep) and rep[i] is v)
    return ratio(bons, len(sol))


def c_trous(data, sol, rep):
    rep = rep or []
    strict = sol.get("strict", False)
    bons = 0
    for i, acc in enumerate(sol["reponses"]):
        val = norm(rep[i] if i < len(rep) else "", strict)
        if val in [norm(a, strict) for a in acc]:
            bons += 1
    return ratio(bons, len(sol["reponses"]))


def c_quiz(data, sol, rep):
    rep = rep or []
    bons = 0
    for i, attendu in enumerate(sol["reponses"]):
        r = rep[i] if i < len(rep) else None
        if isinstance(attendu, list):          # champ texte
            if compact(r) in [compact(a) for a in attendu]:
                bons += 1
        else:                                   # choix : index
            try:
                if int(r) == attendu:
                    bons += 1
            except (TypeError, ValueError):
                pass
    return ratio(bons, len(sol["reponses"]))


def c_ordre(data, sol, rep):
    """rep : {item: numéro}. Un point par étape à la bonne place."""
    rep = rep or {}
    bons = 0
    for pos, item in enumerate(sol["ordre"], start=1):
        try:
            if int(rep.get(item, 0)) == pos:
                bons += 1
        except (TypeError, ValueError):
            pass
    return ratio(bons, len(sol["ordre"]))


def c_blocs(data, sol, rep):
    rep = rep or []
    bons = sum(1 for i, t in enumerate(sol["ordre"]) if i < len(rep) and rep[i] == t)
    return ratio(bons, len(sol["ordre"]))


def c_grille_clic(data, sol, rep):
    return 20.0 if str(rep or "").upper() in [c.upper() for c in sol["cases"]] else 0.0


def c_texte(data, sol, rep):
    lignes = [l.strip() for l in str(rep or "").splitlines() if l.strip()]
    if sol.get("regle") == "majuscules":
        bonnes = [l for l in lignes if l[0].isalpha() and l[0].isupper()]
        return ratio(min(len(bonnes), sol["min"]), sol["min"])
    return 0.0


# ------------------------------------------------------------------ types pratiques
def c_chemin(data, sol, rep):
    """rep : liste de mouvements 'H','B','G','D'. 20 si le robot arrive sans toucher de mur."""
    g = sol["grille"]
    R = [(i, j) for i, row in enumerate(g) for j, c in enumerate(row) if c == "R"][0]
    cible = [(i, j) for i, row in enumerate(g) for j, c in enumerate(row) if c == "D"][0]
    pas = {"H": (-1, 0), "B": (1, 0), "G": (0, -1), "D": (0, 1)}
    i, j = R
    for m in (rep or [])[:60]:
        if m not in pas:
            return 0.0
        i, j = i + pas[m][0], j + pas[m][1]
        if not (0 <= i < len(g) and 0 <= j < len(g[0])) or g[i][j] == "#":
            return 0.0
        if (i, j) == cible:
            return 20.0
    return 0.0


def c_fenetre(data, sol, rep):
    """rep : journal des actions. 5 points par étape faite dans l'ordre."""
    etapes, k = sol["etapes"], 0
    for a in (rep or [])[:50]:
        if k < len(etapes) and a == etapes[k]:
            k += 1
    return ratio(k, len(etapes))


def c_affiche(data, sol, rep):
    rep = rep or {}
    pts = 0
    try:
        taille = int(rep.get("taille", 0))
    except (TypeError, ValueError):
        taille = 0
    titre = str(rep.get("titre", "")).strip()
    phrases = str(rep.get("texte", "")).strip()
    nb_mots = len(phrases.split())
    for r in sol["regles"]:
        if r == "grand_titre" and titre and taille >= 28 and rep.get("gras"):
            pts += 1
        elif r == "image" and rep.get("image"):
            pts += 1
        elif r == "peu_de_mots" and 3 <= nb_mots <= 30:
            pts += 1
        elif r == "centre" and rep.get("align") == "center":
            pts += 1
    return ratio(pts, len(sol["regles"]))


def c_frappe(data, sol, rep):
    """rep : {texte: ce que l'élève a tapé}. On compte les mots justes, dans l'ordre du modèle répété."""
    rep = rep or {}
    modele = data["texte"].split()
    tape = str(rep.get("texte", ""))[:4000].split()
    if not tape:
        return 0.0
    import difflib
    cible = modele * (len(tape) // len(modele) + 2)
    sm = difflib.SequenceMatcher(None, cible, tape, autojunk=False)
    justes = sum(b.size for b in sm.get_matching_blocks())
    return ratio(min(justes, sol["mots_cible"]), sol["mots_cible"])


def c_dossiers(data, sol, rep):
    """rep : {arbre: {...}} état final de l'ordinateur simulé. Un point par but atteint."""
    arbre = (rep or {}).get("arbre") or {}
    if not arbre:
        return 0.0

    def trouve(chemin):
        noeud = arbre
        for part in chemin.split("/"):
            if not isinstance(noeud, dict) or part not in noeud:
                return False, None
            noeud = noeud[part]
        return True, noeud

    bons = 0
    for but in sol["buts"]:
        if "existe" in but:
            ok, n = trouve(but["existe"])
            if ok and (not but.get("dossier") or isinstance(n, dict)):
                bons += 1
        elif "absent" in but:
            ok, _ = trouve(but["absent"])
            if not ok:
                bons += 1
    return ratio(bons, len(sol["buts"]))


CORRECTEURS = {
    "relier": c_relier, "classer": c_classer, "vraifaux": c_vraifaux, "trous": c_trous, "quiz": c_quiz,
    "ordre": c_ordre, "blocs": c_blocs, "grille_clic": c_grille_clic, "texte": c_texte, "chemin": c_chemin,
    "fenetre": c_fenetre, "affiche": c_affiche, "frappe": c_frappe, "dossiers": c_dossiers,
}


def corriger(exercice, reponse):
    f = CORRECTEURS.get(exercice["type"])
    if not f:
        return 0.0
    try:
        return f(exercice.get("data", {}), exercice["solution"], reponse)
    except Exception:
        return 0.0
