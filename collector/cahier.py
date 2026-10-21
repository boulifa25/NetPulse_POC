"""
Le cahier : enregistre chaque mesure du gardien dans PostgreSQL.

La base tourne dans Docker (service "base" du docker-compose.yml) : docker compose up -d base
Adresse par défaut : postgresql://netpulse:netpulse@127.0.0.1:5433/netpulse
(à changer avec la variable d'environnement NETPULSE_DB si besoin).
"""
import os
import time
from pathlib import Path

import psycopg

import normes
import regles
from bornes import BORNES, SITES

ADRESSE_BASE = os.environ.get(
    "NETPULSE_DB", "postgresql://netpulse:netpulse@127.0.0.1:5433/netpulse"
)
SCHEMA = Path(__file__).resolve().parent.parent / "database" / "schema.sql"
REAPPRENDRE_TOUTES_LES = 3600  # secondes : le gardien malin met ses normes à jour chaque heure


def connecter():
    return psycopg.connect(ADRESSE_BASE, autocommit=True, connect_timeout=3)


class Cahier:
    """Garde une connexion ouverte et la rouvre toute seule si la base a redémarré."""

    def __init__(self):
        self.connexion = None
        self.appris_a = None  # instant du dernier apprentissage des normes

    def ouvrir(self):
        self.connexion = connecter()
        with self.connexion.transaction():
            # Crée les tables si besoin, puis enregistre l'inventaire (sites + bornes).
            self.connexion.execute(SCHEMA.read_text(encoding="utf-8"))
            for nom, type_site in SITES.items():
                self.connexion.execute(
                    "INSERT INTO sites (nom, type) VALUES (%s, %s) "
                    "ON CONFLICT (nom) DO UPDATE SET type = EXCLUDED.type",
                    (nom, type_site),
                )
            for site, nom, port in BORNES:
                self.connexion.execute(
                    "INSERT INTO bornes (nom, site_id, port) "
                    "VALUES (%s, (SELECT id FROM sites WHERE nom = %s), %s) "
                    "ON CONFLICT (nom) DO UPDATE SET site_id = EXCLUDED.site_id, port = EXCLUDED.port",
                    (nom, site, port),
                )

    def enregistrer(self, resultats):
        """Écrit une mesure par borne, puis met les alertes à jour selon les règles.

        Renvoie (alertes_ouvertes, alertes_fermees, creneaux_appris) : les deux listes de dicts
        servent à l'affichage ; creneaux_appris vaut None si les normes n'ont pas été réapprises.
        Lève psycopg.OperationalError si la base est injoignable.
        """
        try:
            if self.connexion is None or self.connexion.closed:
                self.ouvrir()
            # Une seule transaction par tour : toutes les mesures du tour ont la même heure (now()).
            with self.connexion.transaction(), self.connexion.cursor() as curseur:
                curseur.executemany(
                    "INSERT INTO mesures (borne_id, en_ligne, clients, allumee_depuis_s, erreur) "
                    "SELECT id, %s, %s, %s, %s FROM bornes WHERE nom = %s",
                    [
                        (
                            not r["erreur"],
                            None if r["erreur"] else int(r["clients"]),
                            None if r["erreur"] else int(r["uptime"]) // 100,
                            r["erreur"],
                            r["nom"],
                        )
                        for r in resultats
                    ],
                )
                curseur.executemany(
                    "UPDATE bornes SET emplacement = %s "
                    "WHERE nom = %s AND emplacement IS DISTINCT FROM %s",
                    [(r["emplacement"], r["nom"], r["emplacement"])
                     for r in resultats if not r["erreur"]],
                )
                creneaux_appris = None
                if self.appris_a is None or time.monotonic() - self.appris_a > REAPPRENDRE_TOUTES_LES:
                    creneaux_appris = normes.apprendre(curseur)
                    self.appris_a = time.monotonic()
                ouvertes, fermees = self._mettre_a_jour_alertes(curseur, resultats)
                return ouvertes, fermees, creneaux_appris
        except psycopg.OperationalError:
            self.fermer()
            raise

    def _mettre_a_jour_alertes(self, curseur, resultats):
        """Ouvre les alertes nouvelles et ferme celles dont le problème a disparu.

        Une alerte "panne" fermée parce que tout son site est tombé n'est pas terminée : elle est
        regroupée dans l'alerte du site (colonne regroupee_dans, clé "regroupee_dans" du dict).
        """
        # La cible d'une alerte est une borne ou un site (étape 7) : on récupère le nom de l'un ou l'autre.
        curseur.execute(
            "SELECT a.id, coalesce(b.nom, s.nom), a.type, a.message FROM alertes a "
            "LEFT JOIN bornes b ON b.id = a.borne_id "
            "LEFT JOIN sites s ON s.id = a.site_id "
            "WHERE a.fin IS NULL"
        )
        en_cours = {(cible, type_): (id_, message)
                    for id_, cible, type_, message in curseur.fetchall()}
        recentes = normes.dernieres_mesures(curseur, regles.TOURS_ANOMALIE)
        actives = regles.evaluer(resultats, set(en_cours), recentes)

        # Alertes de site actives après ce tour (déjà ouvertes ou ouvertes ci-dessous) : site -> id
        alerte_du_site = {cible: en_cours[(cible, type_)][0]
                          for cible, type_ in actives if (cible, type_) in en_cours
                          and type_ in regles.TYPES_SITE}

        ouvertes = []
        for (cible, type_), (gravite, message) in actives.items():
            if (cible, type_) in en_cours:
                continue  # déjà ouverte : rien à faire
            table, colonne = ("sites", "site_id") if type_ in regles.TYPES_SITE else ("bornes", "borne_id")
            curseur.execute(
                f"INSERT INTO alertes ({colonne}, type, gravite, message) "
                f"SELECT id, %s, %s, %s FROM {table} WHERE nom = %s RETURNING id",
                (type_, gravite, message, cible),
            )
            id_ = curseur.fetchone()[0]
            if type_ in regles.TYPES_SITE:
                alerte_du_site[cible] = id_
            ouvertes.append({"id": id_, "type": type_, "gravite": gravite, "message": message})

        site_de_la_borne = {nom: site for site, nom, _ in BORNES}
        fermees = []
        for (cible, type_), (id_, message) in en_cours.items():
            if (cible, type_) in actives:
                continue  # le problème dure
            # Une borne en panne dont tout le site vient de tomber : regroupée, pas terminée.
            regroupee_dans = (alerte_du_site.get(site_de_la_borne.get(cible))
                              if type_ == "panne" else None)
            curseur.execute(
                "UPDATE alertes SET fin = now(), regroupee_dans = %s WHERE id = %s "
                "RETURNING fin - debut", (regroupee_dans, id_),
            )
            fermees.append({"id": id_, "type": type_, "message": message,
                            "duree_s": curseur.fetchone()[0].total_seconds(),
                            "regroupee_dans": regroupee_dans})
        return ouvertes, fermees

    def fermer(self):
        if self.connexion is not None:
            self.connexion.close()
            self.connexion = None
