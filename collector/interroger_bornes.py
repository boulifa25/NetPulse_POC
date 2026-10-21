"""
Étape 2 : le "gardien" interroge les 10 bornes EN MÊME TEMPS et affiche un bilan par site.

Lancer :  python interroger_bornes.py
(les bornes doivent tourner : docker compose up -d)
"""
import asyncio
from itertools import groupby

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from bornes import ADRESSE, BORNES, COMMUNITY

# Mêmes questions qu'à l'étape 1 (voir interroger_borne.py pour le détail des OID).
QUESTIONS = {
    "nom": "1.3.6.1.2.1.1.5.0",           # sysName
    "emplacement": "1.3.6.1.2.1.1.6.0",   # sysLocation
    "uptime": "1.3.6.1.2.1.1.3.0",        # sysUpTime (1/100 s)
    "clients": "1.3.6.1.4.1.8072.1.3.2.3.1.1.7.99.108.105.101.110.116.115",
}


async def interroger(site, nom, port):
    """Pose les questions à une borne. Renvoie un dict ; "erreur" est rempli si elle ne répond pas."""
    resultat = {"site": site, "nom": nom, "port": port, "erreur": None}

    # Un moteur (donc une socket UDP) PAR borne : sous Windows, une borne éteinte fait
    # remonter une erreur "connexion réinitialisée" qui casse la socket. Partagée, elle
    # ferait croire que d'autres bornes, pourtant allumées, sont en panne.
    moteur = SnmpEngine()
    cible = await UdpTransportTarget.create((ADRESSE, port), timeout=2, retries=1)
    erreur, statut, _, reponses = await get_cmd(
        moteur,
        CommunityData(COMMUNITY, mpModel=1),  # SNMP v2c
        cible,
        ContextData(),
        *[ObjectType(ObjectIdentity(oid)) for oid in QUESTIONS.values()],
    )
    moteur.close_dispatcher()

    if erreur:
        resultat["erreur"] = str(erreur)
    elif statut:
        resultat["erreur"] = f"Erreur SNMP : {statut.prettyPrint()}"
    else:
        for cle, (_, valeur) in zip(QUESTIONS, reponses):
            resultat[cle] = valeur.prettyPrint()
    return resultat


async def interroger_toutes():
    # gather lance les 10 interrogations en parallèle : ~4 s au pire, pas 10 x 4 s.
    return await asyncio.gather(*[interroger(site, nom, port) for site, nom, port in BORNES])


def afficher(resultats):
    for site, bornes_du_site in groupby(resultats, key=lambda r: r["site"]):
        bornes_du_site = list(bornes_du_site)
        en_ligne = [r for r in bornes_du_site if not r["erreur"]]
        total_clients = sum(int(r["clients"]) for r in en_ligne)
        print(f"\n{site} : {len(en_ligne)}/{len(bornes_du_site)} bornes en ligne, "
              f"{total_clients} clients WiFi")

        for r in bornes_du_site:
            if r["erreur"]:
                print(f"  [PANNE] {r['nom']:<20} (port {r['port']}) : {r['erreur']}")
            else:
                print(f"  [OK]    {r['nom']:<20} {r['emplacement']:<32} "
                      f"{r['clients']:>3} clients")

    en_panne = sum(1 for r in resultats if r["erreur"])
    print(f"\nBilan : {len(resultats) - en_panne}/{len(resultats)} bornes en ligne.")


if __name__ == "__main__":
    afficher(asyncio.run(interroger_toutes()))
