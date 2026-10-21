"""
Étape 8 : l'API. Un serveur web qui donne accès, en lecture seule, à ce que le gardien a
enregistré : sites, bornes, mesures, normes apprises et alertes.

Étape 9 : elle sert aussi l'écran de contrôle (ecran.html) à la racine.

Lancer :  python api.py
Puis ouvrir :  http://127.0.0.1:8000/       (l'écran de contrôle)
               http://127.0.0.1:8000/docs   (documentation interactive, chaque route s'y teste)

L'API ne fait que LIRE la base : c'est toujours le gardien qui interroge les bornes et écrit.
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import psycopg
import psycopg_pool
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from bornes import FUSEAU_HORAIRE
from cahier import ADRESSE_BASE, Cahier

PORT = 8000
ECRAN = Path(__file__).with_name("ecran.html")
# Au-delà de ce délai sans nouvelle mesure, on considère que le gardien ne tourne plus
# (3 tours de 30 s manqués, plus de la marge).
GARDIEN_ACTIF_SI_MESURE_DEPUIS_MOINS_DE_S = 120

journal = logging.getLogger("netpulse.api")


def regler_connexion(connexion):
    # Les dates renvoyées par l'API sont à l'heure locale des sites (ex. 2026-10-21T17:25:01+01:00).
    connexion.execute("SELECT set_config('TimeZone', %s, false)", (FUSEAU_HORAIRE,))


pool = psycopg_pool.ConnectionPool(
    ADRESSE_BASE, min_size=1, max_size=5, open=False, timeout=3,
    kwargs={"autocommit": True, "connect_timeout": 3}, configure=regler_connexion,
)


@asynccontextmanager
async def cycle_de_vie(_app):
    try:
        cahier = Cahier()
        cahier.ouvrir()  # crée les tables si le gardien n'a encore jamais tourné
        cahier.fermer()
    except psycopg.OperationalError as erreur:
        journal.warning("Base injoignable au démarrage (%s) : l'API répondra 503 en attendant.", erreur)
    pool.open(wait=False)
    yield
    pool.close()


app = FastAPI(
    title="NetPulse",
    description="Surveillance des bornes WiFi : sites, bornes, mesures, normes apprises et alertes. "
                "Lecture seule ; les données sont écrites par le gardien.",
    version="0.9.0",
    lifespan=cycle_de_vie,
)


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(psycopg_pool.PoolTimeout)
async def base_injoignable(_request: Request, erreur: Exception):
    return JSONResponse(status_code=503, content={
        "detail": "Base de données injoignable. Vérifie qu'elle tourne : docker compose up -d base",
        "erreur": str(erreur).strip().splitlines()[0] if str(erreur).strip() else type(erreur).__name__,
    })


def lire(requete, parametres=()):
    with pool.connection() as connexion:
        return connexion.execute(requete, parametres).fetchall()


# --------------------------------------------------------------------------- modèles de réponse

class Borne(BaseModel):
    nom: str
    site_id: int
    site: str
    port: int
    emplacement: str | None
    en_ligne: bool | None          # d'après la dernière mesure ; None si jamais mesurée
    clients: int | None
    allumee_depuis_s: int | None
    derniere_mesure: datetime | None


class Site(BaseModel):
    id: int
    nom: str
    type: Literal["hotel", "residence", "magasin"]
    etat: Literal["operationnel", "degrade", "hors_service", "inconnu"]
    nb_bornes: int
    bornes_en_ligne: int
    clients: int
    alertes_en_cours: int


class Alerte(BaseModel):
    id: int
    type: Literal["panne", "surcharge", "anomalie", "site_hors_service"]
    gravite: Literal["critique", "avertissement"]
    message: str
    site: str
    borne: str | None              # None pour une alerte qui vise un site entier
    debut: datetime
    fin: datetime | None
    en_cours: bool
    duree_s: int                   # jusqu'à maintenant si l'alerte est en cours
    regroupee_dans: int | None     # étape 7 : alerte de site qui l'a remplacée


class SiteDetail(Site):
    bornes: list[Borne]
    alertes: list[Alerte]          # alertes en cours sur le site ou ses bornes


class BorneDetail(Borne):
    alertes: list[Alerte]          # alertes en cours sur cette borne


class Mesure(BaseModel):
    horodatage: datetime
    en_ligne: bool
    clients: int | None
    allumee_depuis_s: int | None
    erreur: str | None
    simulee: bool


class Norme(BaseModel):
    heure: int
    clients_habituels: float       # médiane apprise
    ecart_habituel: float
    nb_mesures: int
    appris_le: datetime


class PointHistorique(BaseModel):
    debut: datetime                # début du créneau (créneaux de `pas_minutes`)
    clients: int                   # clients sur l'ensemble des bornes du site
    attendu: float | None          # ce que le gardien malin juge normal à cette heure (somme des médianes)
    bornes_en_ligne: int
    simulee: bool                  # créneau issu de l'historique simulé de l'étape 6


class Sante(BaseModel):
    api: Literal["ok"]
    base: bool
    derniere_mesure: datetime | None
    gardien_actif: bool            # une vraie mesure a été enregistrée il y a peu


# --------------------------------------------------------------------------- requêtes

BORNES = """
SELECT b.nom, s.id, s.nom, b.port, b.emplacement,
       m.en_ligne, m.clients, m.allumee_depuis_s, m.horodatage
FROM bornes b
JOIN sites s ON s.id = b.site_id
LEFT JOIN LATERAL (
    SELECT * FROM mesures WHERE borne_id = b.id AND NOT simulee
    ORDER BY horodatage DESC LIMIT 1
) m ON true
WHERE (%(borne)s::text IS NULL OR b.nom = %(borne)s)
  AND (%(site_id)s::int IS NULL OR s.id = %(site_id)s)
ORDER BY b.port
"""

ALERTES = """
SELECT a.id, a.type, a.gravite, a.message, s.nom, b.nom, a.debut, a.fin, a.fin IS NULL,
       extract(epoch FROM coalesce(a.fin, now()) - a.debut)::int, a.regroupee_dans
FROM alertes a
LEFT JOIN bornes b ON b.id = a.borne_id
JOIN sites s ON s.id = coalesce(a.site_id, b.site_id)
WHERE (%(id)s::bigint IS NULL OR a.id = %(id)s)
  AND (%(en_cours)s::bool IS NULL OR (a.fin IS NULL) = %(en_cours)s)
  AND (%(type)s::text IS NULL OR a.type = %(type)s)
  AND (%(gravite)s::text IS NULL OR a.gravite = %(gravite)s)
  AND (%(site_id)s::int IS NULL OR s.id = %(site_id)s)
  AND (%(borne)s::text IS NULL OR b.nom = %(borne)s)
ORDER BY a.debut DESC, a.id DESC
LIMIT %(limite)s
"""


def charger_bornes(borne=None, site_id=None):
    return [Borne(nom=n, site_id=si, site=sn, port=p, emplacement=e, en_ligne=el, clients=c,
                  allumee_depuis_s=u, derniere_mesure=h)
            for n, si, sn, p, e, el, c, u, h in lire(BORNES, {"borne": borne, "site_id": site_id})]


def charger_alertes(id=None, en_cours=None, type=None, gravite=None, site_id=None, borne=None,
                    limite=50):
    lignes = lire(ALERTES, {"id": id, "en_cours": en_cours, "type": type, "gravite": gravite,
                            "site_id": site_id, "borne": borne, "limite": limite})
    return [Alerte(id=i, type=t, gravite=g, message=m, site=s, borne=b, debut=d, fin=f,
                   en_cours=ec, duree_s=du, regroupee_dans=r)
            for i, t, g, m, s, b, d, f, ec, du, r in lignes]


def resumer_site(id_, nom, type_, bornes, alertes_en_cours):
    mesurees = [b for b in bornes if b.en_ligne is not None]
    en_ligne = sum(1 for b in mesurees if b.en_ligne)
    if not mesurees:
        etat = "inconnu"
    elif en_ligne == len(bornes):
        etat = "operationnel"
    elif en_ligne == 0:
        etat = "hors_service"
    else:
        etat = "degrade"
    return dict(id=id_, nom=nom, type=type_, etat=etat, nb_bornes=len(bornes),
                bornes_en_ligne=en_ligne, clients=sum(b.clients or 0 for b in bornes),
                alertes_en_cours=len(alertes_en_cours))


def charger_sites(site_id=None):
    sites = lire("SELECT id, nom, type FROM sites WHERE %(id)s::int IS NULL OR id = %(id)s ORDER BY id",
                 {"id": site_id})
    bornes = charger_bornes(site_id=site_id)
    alertes = charger_alertes(en_cours=True, site_id=site_id, limite=1000)
    return [(id_, nom, type_,
             [b for b in bornes if b.site_id == id_],
             [a for a in alertes if a.site == nom])
            for id_, nom, type_ in sites]


# --------------------------------------------------------------------------- routes

@app.get("/", include_in_schema=False)
def ecran_de_controle():
    return FileResponse(ECRAN, headers={"Cache-Control": "no-store"})


@app.get("/sante", response_model=Sante, tags=["Santé"],
         summary="L'API, la base et le gardien fonctionnent-ils ?")
def sante():
    try:
        ((derniere, age),) = lire(
            "SELECT max(horodatage), extract(epoch FROM now() - max(horodatage)) "
            "FROM mesures WHERE NOT simulee")
    except (psycopg.OperationalError, psycopg_pool.PoolTimeout):
        return Sante(api="ok", base=False, derniere_mesure=None, gardien_actif=False)
    actif = age is not None and age < GARDIEN_ACTIF_SI_MESURE_DEPUIS_MOINS_DE_S
    return Sante(api="ok", base=True, derniere_mesure=derniere, gardien_actif=actif)


@app.get("/sites", response_model=list[Site], tags=["Sites"],
         summary="Les sites et leur état actuel")
def liste_sites():
    return [Site(**resumer_site(*s)) for s in charger_sites()]


@app.get("/sites/{site_id}", response_model=SiteDetail, tags=["Sites"],
         summary="Un site, ses bornes et ses alertes en cours")
def detail_site(site_id: int):
    sites = charger_sites(site_id)
    if not sites:
        raise HTTPException(404, f"Site inconnu : {site_id}. Voir GET /sites pour la liste.")
    id_, nom, type_, bornes, alertes = sites[0]
    return SiteDetail(**resumer_site(id_, nom, type_, bornes, alertes), bornes=bornes, alertes=alertes)


HISTORIQUE_SITE = """
WITH par_borne AS (
    SELECT date_bin(make_interval(mins => %(pas)s), m.horodatage, timestamptz '2000-01-01') AS debut,
           m.borne_id,
           avg(m.clients) AS clients,          -- NULL si la borne n'a pas répondu de tout le créneau
           bool_or(m.en_ligne) AS en_ligne,
           bool_and(m.simulee) AS simulee
    FROM mesures m
    JOIN bornes b ON b.id = m.borne_id
    WHERE b.site_id = %(site_id)s
      AND m.horodatage > now() - make_interval(hours => %(heures)s)
    GROUP BY 1, 2
)
SELECT p.debut,
       round(sum(coalesce(p.clients, 0)))::int,
       sum(n.mediane),
       count(*) FILTER (WHERE p.en_ligne),
       bool_and(p.simulee)
FROM par_borne p
LEFT JOIN normes n
       ON n.borne_id = p.borne_id
      AND n.heure = extract(hour FROM p.debut AT TIME ZONE %(fuseau)s)
GROUP BY p.debut
ORDER BY p.debut
"""


@app.get("/sites/{site_id}/historique", response_model=list[PointHistorique], tags=["Sites"],
         summary="Clients du site au fil du temps, comparés à ce qui est normal (pour les graphiques)")
def historique_site(
    site_id: int,
    heures: int = Query(24, ge=1, le=24 * 14, description="période couverte, en heures"),
    pas_minutes: int = Query(5, ge=1, le=120, description="taille d'un créneau, en minutes"),
):
    if not lire("SELECT 1 FROM sites WHERE id = %s", (site_id,)):
        raise HTTPException(404, f"Site inconnu : {site_id}. Voir GET /sites pour la liste.")
    lignes = lire(HISTORIQUE_SITE, {"site_id": site_id, "heures": heures, "pas": pas_minutes,
                                    "fuseau": FUSEAU_HORAIRE})
    return [PointHistorique(debut=d, clients=c, attendu=a, bornes_en_ligne=e, simulee=s)
            for d, c, a, e, s in lignes]


@app.get("/bornes", response_model=list[Borne], tags=["Bornes"],
         summary="Toutes les bornes et leur dernier état mesuré")
def liste_bornes(site_id: int | None = Query(None, description="ne garder que les bornes de ce site")):
    return charger_bornes(site_id=site_id)


def borne_ou_404(nom):
    bornes = charger_bornes(borne=nom)
    if not bornes:
        raise HTTPException(404, f"Borne inconnue : {nom}. Voir GET /bornes pour la liste.")
    return bornes[0]


@app.get("/bornes/{nom}", response_model=BorneDetail, tags=["Bornes"],
         summary="Une borne, son dernier état et ses alertes en cours")
def detail_borne(nom: str):
    borne = borne_ou_404(nom)
    return BorneDetail(**borne.model_dump(), alertes=charger_alertes(borne=nom, en_cours=True))


@app.get("/bornes/{nom}/mesures", response_model=list[Mesure], tags=["Bornes"],
         summary="L'historique des mesures d'une borne (la plus récente en premier)")
def mesures_borne(
    nom: str,
    limite: int = Query(100, ge=1, le=5000, description="nombre maximum de mesures"),
    depuis: datetime | None = Query(None, description="seulement les mesures après cette date "
                                                      "(ex. 2026-10-21T17:00:00+01:00)"),
    inclure_simulees: bool = Query(False, description="inclure l'historique simulé de l'étape 6"),
):
    borne_ou_404(nom)
    lignes = lire(
        "SELECT m.horodatage, m.en_ligne, m.clients, m.allumee_depuis_s, m.erreur, m.simulee "
        "FROM mesures m JOIN bornes b ON b.id = m.borne_id "
        "WHERE b.nom = %(nom)s AND (%(simulees)s OR NOT m.simulee) "
        "  AND (%(depuis)s::timestamptz IS NULL OR m.horodatage > %(depuis)s) "
        "ORDER BY m.horodatage DESC LIMIT %(limite)s",
        {"nom": nom, "simulees": inclure_simulees, "depuis": depuis, "limite": limite})
    return [Mesure(horodatage=h, en_ligne=e, clients=c, allumee_depuis_s=u, erreur=er, simulee=s)
            for h, e, c, u, er, s in lignes]


@app.get("/bornes/{nom}/normes", response_model=list[Norme], tags=["Bornes"],
         summary="Ce que le gardien malin a appris pour cette borne, heure par heure")
def normes_borne(nom: str):
    borne_ou_404(nom)
    lignes = lire(
        "SELECT n.heure, n.mediane, n.ecart, n.nb, n.appris_le FROM normes n "
        "JOIN bornes b ON b.id = n.borne_id WHERE b.nom = %s ORDER BY n.heure", (nom,))
    return [Norme(heure=h, clients_habituels=m, ecart_habituel=e, nb_mesures=nb, appris_le=a)
            for h, m, e, nb, a in lignes]


@app.get("/alertes", response_model=list[Alerte], tags=["Alertes"],
         summary="Les alertes, les plus récentes en premier")
def liste_alertes(
    en_cours: bool | None = Query(None, description="true : en cours seulement ; false : terminées seulement"),
    type: Literal["panne", "surcharge", "anomalie", "site_hors_service"] | None = None,
    gravite: Literal["critique", "avertissement"] | None = None,
    site_id: int | None = None,
    borne: str | None = Query(None, description="nom de la borne, ex. borne-hotel-02"),
    limite: int = Query(50, ge=1, le=1000),
):
    return charger_alertes(en_cours=en_cours, type=type, gravite=gravite, site_id=site_id,
                           borne=borne, limite=limite)


@app.get("/alertes/{alerte_id}", response_model=Alerte, tags=["Alertes"], summary="Une alerte")
def detail_alerte(alerte_id: int):
    alertes = charger_alertes(id=alerte_id, limite=1)
    if not alertes:
        raise HTTPException(404, f"Alerte inconnue : {alerte_id}.")
    return alertes[0]


if __name__ == "__main__":
    print(f"Écran de contrôle : http://127.0.0.1:{PORT}/")
    print(f"API NetPulse      : http://127.0.0.1:{PORT}/docs  (Ctrl+C pour arrêter)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
