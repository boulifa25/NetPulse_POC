"""
Étape 5 : consulter les alertes enregistrées par le gardien.

  python alertes.py           -> les alertes en cours, puis les 20 dernières terminées
  python alertes.py -n 50     -> les 50 dernières terminées
"""
import argparse
import sys

import psycopg

from cahier import connecter

EN_COURS = """
SELECT a.id, a.type, a.gravite, a.message, a.debut, now() - a.debut, NULL
FROM alertes a
WHERE a.fin IS NULL
ORDER BY a.gravite = 'critique' DESC, a.debut
"""

TERMINEES = """
SELECT a.id, a.type, a.gravite, a.message, a.debut, a.fin - a.debut, a.regroupee_dans
FROM alertes a
WHERE a.fin IS NOT NULL
ORDER BY a.fin DESC
LIMIT %s
"""


def heure(moment):
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def duree(intervalle):
    minutes, secondes = divmod(int(intervalle.total_seconds()), 60)
    heures, minutes = divmod(minutes, 60)
    if heures:
        return f"{heures} h {minutes:02d} min"
    return f"{minutes} min {secondes:02d} s" if minutes else f"{secondes} s"


def afficher(lignes):
    for id_, type_, gravite, message, debut, depuis, regroupee_dans in lignes:
        marque = "CRITIQUE" if gravite == "critique" else "AVERTIS."
        suite = f"  -> regroupée dans #{regroupee_dans}" if regroupee_dans else ""
        print(f"  #{id_:<4} {marque:<9} {type_:<17} {heure(debut)}  ({duree(depuis):>12})  "
              f"{message}{suite}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alertes NetPulse.")
    parser.add_argument("-n", type=int, default=20,
                        help="nombre d'alertes terminées à afficher (défaut : 20)")
    args = parser.parse_args()

    try:
        with connecter() as connexion:
            en_cours = connexion.execute(EN_COURS).fetchall()
            terminees = connexion.execute(TERMINEES, (args.n,)).fetchall()
    except psycopg.OperationalError as erreur:
        sys.exit(f"Base injoignable : {erreur}\nVérifie qu'elle tourne : docker compose up -d base")
    except psycopg.errors.UndefinedTable:
        sys.exit("Pas encore de table des alertes : lance le gardien une première fois.")

    print(f"Alertes en cours : {len(en_cours)}  (durée = depuis combien de temps)")
    afficher(en_cours) if en_cours else print("  aucune")
    print(f"\n{len(terminees)} dernières alertes terminées  (durée = combien de temps elles ont duré)")
    afficher(terminees) if terminees else print("  aucune")
