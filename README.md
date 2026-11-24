# Digital Kids Anjanahary · Devoirs en ligne

Site où les élèves font leurs devoirs directement à l'écran : une petite leçon avant chaque exercice, des exercices à pratiquer (clavier, souris, dossiers, affiche, robot, Scratch…), un bouton **Valider** et une **note sur 20** par exercice.

## Ce que fait le site

| Pour l'élève | Pour l'animateur (`/animateur`) |
|---|---|
| Identifiant + code secret à 4 chiffres | Créer les élèves (un prénom par ligne) : identifiant et code automatiques |
| Voit seulement les devoirs de son niveau | Imprimer les fiches de connexion |
| Petite leçon + exercice + « Valider » | Tableau des notes /20 par élève et par devoir |
| Note /20 et corrigé tout de suite | Télécharger les notes (Excel / CSV) |
| Moyenne du devoir à la fin | Ajouter le devoir de la semaine (fichier .json), le retirer, voir l'aperçu |
| | Remettre un devoir à zéro, changer le niveau ou le code d'un élève |

Les réponses sont corrigées **sur le serveur** : les solutions ne sont jamais envoyées au navigateur de l'élève, et une réponse validée ne peut plus être changée (seul l'animateur peut remettre à zéro).

## Mise en ligne (PythonAnywhere gratuit)

1. Créez un compte gratuit sur pythonanywhere.com (le nom du compte devient l'adresse du site, par exemple `digitalkids` → `digitalkids.pythonanywhere.com`).
2. Onglet **Account** → **API Token** → **Create a new API token** → copiez-le.
3. Onglet **Consoles** → **Bash**, puis collez :

```bash
git clone https://github.com/aorn-grou/digitalkids-devoirs.git && python3 digitalkids-devoirs/installer_pythonanywhere.py
```

4. Collez le token quand le script le demande. À la fin, il affiche l'adresse du site.
5. Ouvrez `https://VOTRE-NOM.pythonanywhere.com/animateur` et créez votre mot de passe.

**Compte gratuit :** tous les 3 mois, PythonAnywhere demande de cliquer sur **« Run until 3 months from today »** dans l'onglet Web, sinon le site s'arrête (les données restent).

## Ajouter le devoir de la semaine

- **Le plus simple :** Espace animateur → **Devoirs** → choisissez le fichier `.json` du nouveau devoir → **Ajouter le devoir**.
- **Ou par GitHub :** le fichier est ajouté dans `devoirs/`, puis dans la console Bash : `python3 digitalkids-devoirs/installer_pythonanywhere.py --maj`, puis **Importer les devoirs du dossier** dans l'espace animateur.

## Types d'exercices disponibles

`relier`, `classer`, `vraifaux`, `trous`, `quiz` (champs et choix), `ordre`, `blocs` (Scratch), `grille_clic` (morpion), `texte` (majuscules), `chemin` (robot), `fenetre` (boutons d'une fenêtre), `affiche` (mini-Writer), `frappe` (test de vitesse), `dossiers` (ordinateur simulé).

Les deux premiers devoirs sont générés par `outils/creer_devoirs.py`. Test complet : `python3 outils/test_complet.py`.

## Fichiers

- `app.py` : le site (pages élève et animateur)
- `correction.py` : la correction automatique sur 20
- `devoirs/` : les devoirs (un fichier .json par devoir)
- `templates/`, `static/` : pages et design aux couleurs de Digital Kids
- `donnees/` : la base des élèves et des notes (créée sur le serveur, jamais envoyée sur GitHub)
