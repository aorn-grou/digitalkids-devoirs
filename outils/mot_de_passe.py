"""Mot de passe oublié (administrateur ou animateur).

À lancer dans la console Bash de PythonAnywhere :
    python3.10 digitalkids-devoirs/outils/mot_de_passe.py
Seul le propriétaire du compte PythonAnywhere peut ouvrir cette console : c'est la preuve que c'est bien vous.
"""
import getpass
import os
import sqlite3
import sys

from werkzeug.security import generate_password_hash

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "donnees", "ecole.db")
if not os.path.exists(BASE):
    sys.exit("✗ Base de données introuvable : le site n'a pas encore été démarré.")
con = sqlite3.connect(BASE)
comptes = [("admin", "Administrateur", None)] + [(r[0], r[1], r[2]) for r in con.execute("SELECT identifiant, nom, id FROM profs ORDER BY nom")]
print("=" * 56)
print(" Digital Kids · mot de passe oublié")
print("=" * 56)
for i, (ident, nom, _) in enumerate(comptes, 1):
    print(f"  {i}. {nom:<22} identifiant : {ident}")
choix = input("\nNuméro du compte à réparer : ").strip()
if not choix.isdigit() or not 1 <= int(choix) <= len(comptes):
    sys.exit("✗ Numéro inconnu. Relancez la commande.")
ident, nom, pid = comptes[int(choix) - 1]
while True:
    mdp = getpass.getpass(f"Nouveau mot de passe pour {nom} (6 caractères ou plus, rien ne s'affiche) : ")
    if len(mdp) < 6:
        print("  Trop court, recommencez.")
        continue
    if getpass.getpass("Écrivez-le une 2e fois : ") != mdp:
        print("  Les deux ne sont pas pareils, recommencez.")
        continue
    break
h = generate_password_hash(mdp)
if pid is None:
    con.execute("INSERT OR REPLACE INTO reglages VALUES ('mot_de_passe', ?)", (h,))
else:
    con.execute("UPDATE profs SET mdp=? WHERE id=?", (h, pid))
    try:
        con.execute("UPDATE profs SET oubli=NULL WHERE id=?", (pid,))
    except sqlite3.Error:
        pass
con.commit()
print(f"\n✓ C'est fait. Connectez-vous avec l'identifiant « {ident} » et le nouveau mot de passe.")
