"""
Étape 3 : le gardien automatique.

Toutes les 30 secondes, il interroge les 10 bornes et ne signale que ce qui CHANGE :
  - [PANNE]        une borne qui répondait ne répond plus
  - [RETOUR]       une borne en panne répond de nouveau (avec la durée de la coupure)
  - [REDÉMARRAGE]  une borne répond toujours, mais son compteur "allumée depuis" est
                   reparti de zéro : elle a redémarré entre deux tours sans qu'on la voie tomber
Chaque événement est aussi écrit dans collector/evenements.log.

Étape 4 : chaque mesure (une par borne et par tour) est enregistrée dans PostgreSQL
(voir cahier.py). Si la base ne répond pas, le gardien continue de surveiller, le signale
([CAHIER]) et retente au tour suivant ; les mesures de ces tours-là sont perdues.

Étape 5 : à chaque tour, les règles de regles.py (panne, surcharge) ouvrent ou ferment des
alertes en base ; le gardien les affiche ([ALERTE] / [FIN ALERTE]). Voir alertes.py.

Étape 6 : le gardien malin (normes.py) apprend au démarrage puis chaque heure ce qui est normal
pour chaque borne ([IA]) ; regles.py en tire des alertes "anomalie".

Étape 7 : si toutes les bornes d'un site tombent, regles.py ouvre UNE alerte "site_hors_service"
au lieu d'une alerte par borne ; une panne déjà ouverte sur ce site y est rattachée ([REGROUPÉE]).

Lancer :  python gardien.py                 (Ctrl+C pour arrêter)
          python gardien.py --intervalle 5  (tours plus rapides pour tester)
"""
import argparse
import asyncio
import time
from datetime import datetime
from pathlib import Path

import psycopg

import normes
from cahier import ADRESSE_BASE, Cahier
from interroger_bornes import interroger_toutes

INTERVALLE_PAR_DEFAUT = 30  # secondes entre deux tours
JOURNAL = Path(__file__).with_name("evenements.log")


def horodatage():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def signaler(message):
    heure = horodatage()
    ligne = f"{heure}  {message}"
    print(ligne)
    with JOURNAL.open("a", encoding="utf-8") as journal:
        journal.write(ligne + "\n")


def duree_lisible(secondes):
    minutes, secondes = divmod(int(secondes), 60)
    return f"{minutes} min {secondes:02d} s" if minutes else f"{secondes} s"


def comparer(etats, resultats):
    """Compare ce tour au précédent, signale les changements et met à jour `etats`.

    etats[nom] = {"en_ligne": bool, "depuis": instant du dernier changement, "uptime": int}
    """
    maintenant = time.monotonic()
    for r in resultats:
        nom, en_ligne = r["nom"], not r["erreur"]
        uptime = int(r["uptime"]) if en_ligne else None
        avant = etats.get(nom)

        if avant is None:
            # Premier tour : on note l'état de départ ; seules les pannes méritent un message.
            if not en_ligne:
                signaler(f"[PANNE]       {nom} ({r['site']}) ne répond pas au démarrage du gardien")
            etats[nom] = {"en_ligne": en_ligne, "depuis": maintenant, "uptime": uptime}
            continue

        if avant["en_ligne"] and not en_ligne:
            signaler(f"[PANNE]       {nom} ({r['site']}) ne répond plus : {r['erreur']}")
            avant.update(en_ligne=False, depuis=maintenant)
        elif not avant["en_ligne"] and en_ligne:
            coupure = duree_lisible(maintenant - avant["depuis"])
            signaler(f"[RETOUR]      {nom} ({r['site']}) répond de nouveau (coupure : {coupure})")
            avant.update(en_ligne=True, depuis=maintenant)
        elif en_ligne and avant["uptime"] is not None and uptime < avant["uptime"]:
            signaler(f"[REDÉMARRAGE] {nom} ({r['site']}) a redémarré depuis le dernier tour")

        if en_ligne:
            avant["uptime"] = uptime


async def enregistrer(cahier, resultats, base_ok):
    """Écrit le tour dans la base. Renvoie True si c'est fait ; signale les pertes/retours de la base."""
    try:
        # psycopg est bloquant : on le fait tourner à côté pour ne pas figer la boucle.
        ouvertes, fermees, creneaux_appris = await asyncio.to_thread(cahier.enregistrer, resultats)
    except psycopg.OperationalError as erreur:
        if base_ok is not False:
            motif = str(erreur).strip().splitlines()[0]
            signaler(f"[CAHIER]      base injoignable, mesures non enregistrées : {motif}")
        return False
    if base_ok is False:
        signaler("[CAHIER]      base de nouveau joignable, enregistrement repris")
    if creneaux_appris is not None:
        signaler(f"[IA]          normes apprises : {creneaux_appris} créneaux (borne x heure) "
                 f"sur les {normes.JOURS_APPRENTISSAGE} derniers jours")
    for a in ouvertes:
        signaler(f"[ALERTE]      #{a['id']} {a['type']} ({a['gravite']}) : {a['message']}")
    for a in fermees:
        if a["regroupee_dans"]:
            signaler(f"[REGROUPÉE]   #{a['id']} {a['type']} rattachée à l'alerte de site "
                     f"#{a['regroupee_dans']} : {a['message']}")
        else:
            signaler(f"[FIN ALERTE]  #{a['id']} {a['type']} terminée après "
                     f"{duree_lisible(a['duree_s'])} : {a['message']}")
    return True


def resume(resultats, duree_tour, base_ok):
    """Une ligne par tour, pour voir que le gardien est vivant."""
    en_ligne = [r for r in resultats if not r["erreur"]]
    clients = sum(int(r["clients"]) for r in en_ligne)
    en_panne = [r["nom"] for r in resultats if r["erreur"]]
    cahier = "enregistré" if base_ok else "NON enregistré"
    ligne = (f"{horodatage()}  tour : {len(en_ligne)}/{len(resultats)} bornes en ligne, "
             f"{clients} clients WiFi, {cahier} ({duree_tour:.1f} s)")
    if en_panne:
        ligne += f"  | en panne : {', '.join(en_panne)}"
    print(ligne)


async def surveiller(intervalle):
    """Boucle de surveillance : un tour toutes les `intervalle` secondes."""
    base_affichee = ADRESSE_BASE.split("@")[-1]  # sans l'identifiant ni le mot de passe
    signaler(f"Gardien démarré : surveillance toutes les {intervalle} s, "
             f"mesures enregistrées dans {base_affichee} (Ctrl+C pour arrêter)")
    etats = {}
    cahier = Cahier()
    base_ok = None  # None : pas encore essayé
    try:
        while True:
            debut = time.monotonic()
            resultats = await interroger_toutes()
            comparer(etats, resultats)
            base_ok = await enregistrer(cahier, resultats, base_ok)
            resume(resultats, time.monotonic() - debut, base_ok)
            # On vise un tour toutes les `intervalle` secondes, quel que soit le temps d'interrogation.
            await asyncio.sleep(max(0, intervalle - (time.monotonic() - debut)))
    finally:
        cahier.fermer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gardien NetPulse : surveille les bornes WiFi.")
    parser.add_argument("--intervalle", type=float, default=INTERVALLE_PAR_DEFAUT,
                        help=f"secondes entre deux tours (défaut : {INTERVALLE_PAR_DEFAUT})")
    args = parser.parse_args()
    try:
        asyncio.run(surveiller(args.intervalle))
    except KeyboardInterrupt:
        signaler("Gardien arrêté.")
