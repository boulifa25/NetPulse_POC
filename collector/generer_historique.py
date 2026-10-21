"""
Étape 6 : fabrique un historique simulé, pour que le gardien malin ait de quoi apprendre
sans attendre des jours.

Crée une mesure toutes les 5 minutes pour chaque borne sur les N derniers jours, avec les mêmes
profils de fréquentation que les fausses bornes (simulator/clients_wifi.sh : garder les deux
synchronisés). Ces mesures sont marquées "simulee" : elles servent à l'apprentissage, mais
jamais à décider qu'une borne va mal en ce moment.

Relancer le script remplace l'historique simulé précédent (les vraies mesures ne sont pas touchées).

Lancer :  python generer_historique.py            (7 jours)
          python generer_historique.py --jours 14
"""
import argparse
import sys

import psycopg

import normes
from bornes import FUSEAU_HORAIRE
from cahier import Cahier

GENERER = """
INSERT INTO mesures (borne_id, horodatage, en_ligne, clients, allumee_depuis_s, simulee)
SELECT b.id, t, true,
       CASE s.type
           WHEN 'hotel' THEN
               CASE WHEN h < 7 THEN 2 WHEN h < 12 THEN 8 WHEN h < 18 THEN 12 ELSE 20 END
               + floor(random() * 6)::int
           WHEN 'residence' THEN
               CASE WHEN h < 7 THEN 6 WHEN h < 18 THEN 4 ELSE 18 END
               + floor(random() * 6)::int
           ELSE  -- magasin : quasi vide hors 9 h-20 h
               CASE WHEN h < 9 OR h >= 20 THEN floor(random() * 2)::int
                    ELSE CASE WHEN h < 12 THEN 10 WHEN h < 18 THEN 22 ELSE 14 END
                         + floor(random() * 6)::int
               END
       END,
       extract(epoch FROM t - debut)::bigint,  -- "allumée depuis" : depuis le début de l'historique
       true
FROM bornes b
JOIN sites s ON s.id = b.site_id
CROSS JOIN (SELECT now() - make_interval(days => %(jours)s) AS debut) d
CROSS JOIN LATERAL generate_series(d.debut, now() - interval '5 minutes', interval '5 minutes') AS t
CROSS JOIN LATERAL (SELECT extract(hour FROM t AT TIME ZONE %(fuseau)s)::int AS h) heure
"""

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Génère un historique simulé pour l'apprentissage.")
    parser.add_argument("--jours", type=int, default=7, help="nombre de jours d'historique (défaut : 7)")
    args = parser.parse_args()

    try:
        cahier = Cahier()
        cahier.ouvrir()  # crée les tables et l'inventaire si besoin
        with cahier.connexion as connexion, connexion.transaction(), connexion.cursor() as curseur:
            curseur.execute("DELETE FROM mesures WHERE simulee")
            supprimees = curseur.rowcount
            curseur.execute(GENERER, {"jours": args.jours, "fuseau": FUSEAU_HORAIRE})
            creees = curseur.rowcount
            creneaux = normes.apprendre(curseur)
    except psycopg.OperationalError as erreur:
        sys.exit(f"Base injoignable : {erreur}\nVérifie qu'elle tourne : docker compose up -d base")

    if supprimees:
        print(f"{supprimees} anciennes mesures simulées supprimées.")
    print(f"{creees} mesures simulées créées ({args.jours} jours, une toutes les 5 min par borne).")
    print(f"Le gardien malin a appris {creneaux} créneaux (borne x heure).")
    print("Voir ce qu'il a appris :  python collector\\normes.py borne-hotel-03")
