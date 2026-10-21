"""
Étape 6 : le gardien malin. Il apprend ce qui est NORMAL pour chaque borne, heure par heure,
et repère les mesures qui sortent de l'ordinaire.

Apprendre : pour chaque borne et chaque heure de la journée (heure locale), on prend toutes
les mesures des JOURS_APPRENTISSAGE derniers jours et on retient :
  - la médiane du nombre de clients (la valeur "typique") ;
  - l'écart habituel autour de cette médiane (MAD : l'écart médian, ramené à l'échelle d'un
    écart-type). Médiane et MAD ignorent les valeurs extrêmes : une surcharge de test à 67
    clients ne fausse pas ce qui est "normal".

Détecter : une mesure est bizarre si elle s'écarte de la médiane d'au moins Z fois l'écart
habituel ET d'au moins quelques clients (pour ne pas crier au loup pour 1 client la nuit).
La décision d'ouvrir ou fermer une alerte est prise dans regles.py.

Lancer :  python normes.py                 -> apprend, puis affiche le bilan
          python normes.py borne-hotel-03  -> ce qui est normal pour cette borne, heure par heure
"""
import argparse
import sys

import psycopg

from bornes import FUSEAU_HORAIRE

JOURS_APPRENTISSAGE = 14   # on apprend sur les 2 dernières semaines
MESURES_MINIMUM = 20       # en dessous, pas assez de recul : pas de détection pour ce créneau

APPRENDRE = """
WITH m AS (
    SELECT borne_id,
           extract(hour FROM horodatage AT TIME ZONE %(fuseau)s)::int AS heure,
           clients
    FROM mesures
    WHERE en_ligne AND horodatage > now() - make_interval(days => %(jours)s)
),
med AS (
    SELECT borne_id, heure, count(*) AS nb,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY clients) AS mediane
    FROM m GROUP BY borne_id, heure
),
mad AS (
    SELECT m.borne_id, m.heure,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(m.clients - med.mediane)) AS mad
    FROM m JOIN med USING (borne_id, heure)
    GROUP BY m.borne_id, m.heure
)
INSERT INTO normes (borne_id, heure, mediane, ecart, nb, appris_le)
SELECT borne_id, heure, mediane,
       greatest(1.4826 * mad, 1.0),   -- 1.4826 : convertit le MAD en équivalent écart-type
       nb, now()
FROM med JOIN mad USING (borne_id, heure)
WHERE nb >= %(minimum)s
ON CONFLICT (borne_id, heure) DO UPDATE
    SET mediane = EXCLUDED.mediane, ecart = EXCLUDED.ecart,
        nb = EXCLUDED.nb, appris_le = EXCLUDED.appris_le
"""

# Les K dernières VRAIES mesures de chaque borne, chacune avec la norme de son heure.
DERNIERES_MESURES = """
SELECT b.nom, m.clients, n.mediane, n.ecart,
       extract(hour FROM m.horodatage AT TIME ZONE %(fuseau)s)::int AS heure
FROM bornes b
CROSS JOIN LATERAL (
    SELECT clients, horodatage FROM mesures
    WHERE borne_id = b.id AND NOT simulee
    ORDER BY horodatage DESC LIMIT %(k)s
) m
LEFT JOIN normes n
       ON n.borne_id = b.id
      AND n.heure = extract(hour FROM m.horodatage AT TIME ZONE %(fuseau)s)
ORDER BY b.nom, m.horodatage DESC
"""


def apprendre(curseur):
    """(Ré)apprend les normes à partir de l'historique. Renvoie le nombre de créneaux appris."""
    curseur.execute(APPRENDRE, {"fuseau": FUSEAU_HORAIRE, "jours": JOURS_APPRENTISSAGE,
                                "minimum": MESURES_MINIMUM})
    return curseur.rowcount


def dernieres_mesures(curseur, k):
    """{nom_borne: [mesure, ...]} du plus récent au plus ancien ; mesure = dict
    clients / mediane / ecart / heure (mediane et ecart à None si rien d'appris pour cette heure,
    clients à None si la borne n'a pas répondu)."""
    curseur.execute(DERNIERES_MESURES, {"fuseau": FUSEAU_HORAIRE, "k": k})
    par_borne = {}
    for nom, clients, mediane, ecart, heure in curseur.fetchall():
        par_borne.setdefault(nom, []).append(
            {"clients": clients, "mediane": mediane, "ecart": ecart, "heure": heure})
    return par_borne


def est_bizarre(mesure, z, ecart_minimum):
    """Vrai si la mesure s'écarte de la norme d'au moins z écarts ET d'au moins ecart_minimum clients."""
    if mesure["clients"] is None or mesure["mediane"] is None:
        return False  # borne muette (c'est une panne, pas une anomalie) ou rien d'appris
    distance = abs(mesure["clients"] - mesure["mediane"])
    return distance >= ecart_minimum and distance >= z * mesure["ecart"]


def afficher_norme_borne(connexion, nom):
    lignes = connexion.execute(
        "SELECT n.heure, n.mediane, n.ecart, n.nb FROM normes n JOIN bornes b ON b.id = n.borne_id "
        "WHERE b.nom = %s ORDER BY n.heure", (nom,)).fetchall()
    if not lignes:
        sys.exit(f"Rien d'appris pour {nom} (borne inconnue, ou pas assez d'historique).")
    print(f"Ce qui est normal pour {nom} (heure locale) :")
    print("  heure   clients habituels   (mesures)")
    for heure, mediane, ecart, nb in lignes:
        bas, haut = max(0, mediane - 2 * ecart), mediane + 2 * ecart
        barre = "#" * round(mediane)
        print(f"  {heure:02d} h   {mediane:5.1f}  [{bas:4.1f} à {haut:4.1f}]  ({nb:>4})  {barre}")


if __name__ == "__main__":
    from cahier import Cahier

    parser = argparse.ArgumentParser(description="Normes apprises par le gardien malin.")
    parser.add_argument("borne", nargs="?", help="nom de la borne (ex. borne-hotel-03)")
    args = parser.parse_args()
    try:
        cahier = Cahier()
        cahier.ouvrir()  # crée les tables si besoin
        with cahier.connexion as connexion:
            if args.borne:
                afficher_norme_borne(connexion, args.borne)
            else:
                with connexion.cursor() as curseur:
                    nb = apprendre(curseur)
                total = connexion.execute("SELECT count(*), count(DISTINCT borne_id) FROM normes").fetchone()
                print(f"Apprentissage : {nb} créneaux (borne x heure) appris ou mis à jour.")
                print(f"Normes en base : {total[0]} créneaux pour {total[1]} bornes (24 max par borne).")
    except psycopg.OperationalError as erreur:
        sys.exit(f"Base injoignable : {erreur}\nVérifie qu'elle tourne : docker compose up -d base")
