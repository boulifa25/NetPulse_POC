"""
Étape 4 : relire le cahier.

  python historique.py                    -> bilan de chaque borne depuis le début
  python historique.py borne-hotel-01     -> les 20 dernières mesures de cette borne
  python historique.py borne-hotel-01 -n 50

Seules les vraies mesures sont affichées (pas celles inventées par generer_historique.py).
"""
import argparse
import sys

import psycopg

from cahier import connecter

BILAN = """
SELECT s.nom, b.nom,
       count(m.id)                                                  AS mesures,
       round(100.0 * count(*) FILTER (WHERE m.en_ligne) / nullif(count(m.id), 0), 1)
                                                                    AS pct_en_ligne,
       round(avg(m.clients), 1)                                     AS clients_moyens,
       max(m.clients)                                               AS clients_max,
       min(m.horodatage)                                            AS premiere,
       max(m.horodatage)                                            AS derniere
FROM bornes b
JOIN sites s ON s.id = b.site_id
LEFT JOIN mesures m ON m.borne_id = b.id AND NOT m.simulee
GROUP BY s.nom, b.nom
ORDER BY min(b.port)
"""

DERNIERES_MESURES = """
SELECT m.horodatage, m.en_ligne, m.clients, m.allumee_depuis_s, m.erreur
FROM mesures m
JOIN bornes b ON b.id = m.borne_id
WHERE b.nom = %s AND NOT m.simulee
ORDER BY m.horodatage DESC
LIMIT %s
"""


def heure(moment):
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S") if moment else "-"


def afficher_bilan(connexion):
    lignes = connexion.execute(BILAN).fetchall()
    print(f"{'Site':<18} {'Borne':<20} {'Mesures':>7} {'En ligne':>9} {'Clients moy/max':>16}  "
          f"{'Première mesure':<19}  {'Dernière mesure':<19}")
    for site, borne, mesures, pct, moyenne, maximum, premiere, derniere in lignes:
        pct = f"{pct} %" if pct is not None else "-"
        clients = f"{moyenne if moyenne is not None else '-'} / {maximum if maximum is not None else '-'}"
        print(f"{site:<18} {borne:<20} {mesures:>7} {pct:>9} {clients:>16}  "
              f"{heure(premiere):<19}  {heure(derniere):<19}")


def afficher_borne(connexion, nom, nombre):
    if connexion.execute("SELECT 1 FROM bornes WHERE nom = %s", (nom,)).fetchone() is None:
        sys.exit(f"Borne inconnue : {nom}. Lance « python historique.py » pour voir la liste.")
    mesures = connexion.execute(DERNIERES_MESURES, (nom, nombre)).fetchall()
    if not mesures:
        print(f"Aucune mesure pour {nom} : le gardien a-t-il tourné ?")
        return
    print(f"{len(mesures)} dernières mesures de {nom} (la plus récente en haut) :")
    for moment, en_ligne, clients, allumee_depuis_s, erreur in mesures:
        if en_ligne:
            print(f"  {heure(moment)}  [OK]     {clients:>3} clients   allumée depuis {allumee_depuis_s} s")
        else:
            print(f"  {heure(moment)}  [PANNE]  {erreur}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relire l'historique des bornes NetPulse.")
    parser.add_argument("borne", nargs="?", help="nom de la borne (ex. borne-hotel-01)")
    parser.add_argument("-n", type=int, default=20, help="nombre de mesures à afficher (défaut : 20)")
    args = parser.parse_args()

    try:
        with connecter() as connexion:
            if args.borne:
                afficher_borne(connexion, args.borne, args.n)
            else:
                afficher_bilan(connexion)
    except psycopg.OperationalError as erreur:
        sys.exit(f"Base injoignable : {erreur}\nVérifie qu'elle tourne : docker compose up -d base")
