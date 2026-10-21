"""
Inventaire des bornes : qui elles sont, sur quel site, et à quel port les joindre.
Garder cette liste synchronisée avec docker-compose.yml.
"""

ADRESSE = "127.0.0.1"  # toutes les fausses bornes tournent sur ton PC
COMMUNITY = "public"

# Fuseau horaire des sites : sert à savoir "quelle heure il est" pour une borne (étape 6).
# Doit être le même que TZ dans simulator/bornes.env. Etc/GMT-1 = UTC+1, sans heure d'été.
FUSEAU_HORAIRE = "Etc/GMT-1"

# Les 3 sites et leur type
SITES = {
    "Hotel Paris": "hotel",
    "Residence Lyon": "residence",
    "Magasin Marseille": "magasin",
}

BORNES = [
    # (site, nom, port)
    ("Hotel Paris", "borne-hotel-01", 1161),
    ("Hotel Paris", "borne-hotel-02", 1162),
    ("Hotel Paris", "borne-hotel-03", 1163),
    ("Hotel Paris", "borne-hotel-04", 1164),
    ("Residence Lyon", "borne-residence-01", 1165),
    ("Residence Lyon", "borne-residence-02", 1166),
    ("Residence Lyon", "borne-residence-03", 1167),
    ("Magasin Marseille", "borne-magasin-01", 1168),
    ("Magasin Marseille", "borne-magasin-02", 1169),
    ("Magasin Marseille", "borne-magasin-03", 1170),
]
