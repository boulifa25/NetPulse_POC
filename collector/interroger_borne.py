"""
Étape 1 : le "gardien" frappe à la porte d'UNE borne et lui pose 4 questions.

Lancer :  python interroger_borne.py
(la borne doit tourner : docker compose up -d)
"""
import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

ADRESSE_BORNE = "127.0.0.1"
PORT_BORNE = 1161
COMMUNITY = "public"

# Chaque question SNMP a un identifiant numérique appelé OID.
QUESTIONS = {
    "Nom de la borne": "1.3.6.1.2.1.1.5.0",           # sysName
    "Emplacement": "1.3.6.1.2.1.1.6.0",               # sysLocation
    "Allumée depuis (1/100 s)": "1.3.6.1.2.1.1.3.0",  # sysUpTime
    # Notre métrique "extend clients" (nsExtendOutput1Line."clients")
    "Clients WiFi connectés": "1.3.6.1.4.1.8072.1.3.2.3.1.1.7.99.108.105.101.110.116.115",
}


async def interroger():
    moteur = SnmpEngine()
    cible = await UdpTransportTarget.create((ADRESSE_BORNE, PORT_BORNE), timeout=2, retries=1)

    erreur, statut, _, reponses = await get_cmd(
        moteur,
        CommunityData(COMMUNITY, mpModel=1),  # SNMP v2c
        cible,
        ContextData(),
        *[ObjectType(ObjectIdentity(oid)) for oid in QUESTIONS.values()],
    )
    moteur.close_dispatcher()

    if erreur:
        print(f"La borne ne répond pas : {erreur}")
        print("Vérifie qu'elle tourne avec : docker compose ps")
        return
    if statut:
        print(f"Erreur SNMP : {statut.prettyPrint()}")
        return

    print("Réponse de la borne :")
    for libelle, (_, valeur) in zip(QUESTIONS, reponses):
        print(f"  - {libelle} : {valeur.prettyPrint()}")


if __name__ == "__main__":
    asyncio.run(interroger())
