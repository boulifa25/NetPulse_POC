"""
Les règles d'alerte. Toutes les règles sont ici, et seulement ici.

Étape 5 — règles simples :
  - panne     : la borne ne répond pas                         -> alerte critique
  - surcharge : trop de clients connectés à la borne           -> avertissement
                (s'ouvre à SEUIL_SURCHARGE clients, ne se referme que sous SEUIL_FIN_SURCHARGE :
                 sans cet écart, une borne qui oscille autour du seuil ouvrirait et fermerait
                 une alerte à chaque tour)

Étape 6 — le gardien malin :
  - anomalie  : la borne répond, aucune règle simple n'est dépassée, mais son nombre de clients
                n'a rien à voir avec ce qui est normal pour elle à cette heure-ci (voir normes.py)
                pendant TOURS_ANOMALIE tours de suite                -> avertissement

Étape 7 — comprendre une grosse panne :
  - site_hors_service : TOUTES les bornes d'un site (au moins 2) sont muettes au même tour
                -> UNE alerte critique pour le site, à la place des alertes "panne" de ses bornes
                   (une coupure de courant ou d'Internet sur le site, pas 4 bornes cassées)

Le gardien appelle evaluer() à chaque tour ; cahier.py ouvre en base les alertes nouvelles et
ferme celles dont le problème a disparu.
"""
from normes import est_bizarre

TYPES_SITE = {"site_hors_service"}  # types d'alerte qui visent un site entier, pas une borne

SEUIL_SURCHARGE = 35       # clients : à partir de là, la borne est considérée comme saturée
                           # (en temps normal, une borne simulée monte au plus à 27 clients)
SEUIL_FIN_SURCHARGE = 30   # clients : sous ce nombre, la surcharge est terminée

TOURS_ANOMALIE = 3         # tours bizarres d'affilée avant d'alerter (~1 min 30 à 30 s par tour)
Z_ANOMALIE = 4.0           # ouverture : à au moins 4 "écarts habituels" de la normale…
ECART_MIN_ANOMALIE = 6     # … et à au moins 6 clients de la normale
Z_FIN_ANOMALIE = 2.5       # fermeture : dès que la borne revient à moins de 2,5 écarts…
ECART_MIN_FIN_ANOMALIE = 4  # … ou à moins de 4 clients de la normale


def evaluer(resultats, en_cours, recentes):
    """Renvoie les alertes qui DOIVENT être en cours après ce tour.

    resultats : les réponses des bornes de ce tour (voir interroger_bornes.py)
    en_cours  : ensemble des (nom_borne, type) déjà ouvertes en base
    recentes  : {nom_borne: dernières mesures, la plus récente en premier} (voir normes.py)
    Résultat  : {(nom_cible, type): (gravite, message)} ; la cible est une borne, ou un site
                pour le type "site_hors_service" (voir TYPES_SITE)
    """
    actives = {}
    for r in resultats:
        nom, site = r["nom"], r["site"]

        if r["erreur"]:
            actives[(nom, "panne")] = ("critique", f"{nom} ({site}) ne répond plus")
            continue  # une borne muette ne dit rien de ses clients : pas d'autre règle

        clients = int(r["clients"])
        seuil = SEUIL_FIN_SURCHARGE if (nom, "surcharge") in en_cours else SEUIL_SURCHARGE
        if clients >= seuil:
            actives[(nom, "surcharge")] = (
                "avertissement",
                f"{nom} ({site}) : {clients} clients connectés (seuil : {SEUIL_SURCHARGE})",
            )
            continue  # déjà expliqué par une règle simple : pas besoin de l'IA

        mesures = recentes.get(nom, [])
        if (nom, "anomalie") in en_cours:
            # Reste ouverte tant que la dernière mesure est encore nettement hors norme.
            encore = mesures[:1]
            bizarre = bool(encore) and est_bizarre(encore[0], Z_FIN_ANOMALIE, ECART_MIN_FIN_ANOMALIE)
        else:
            serie = mesures[:TOURS_ANOMALIE]
            bizarre = len(serie) == TOURS_ANOMALIE and all(
                est_bizarre(m, Z_ANOMALIE, ECART_MIN_ANOMALIE) for m in serie)
        if bizarre:
            m = mesures[0]
            actives[(nom, "anomalie")] = (
                "avertissement",
                f"{nom} ({site}) : {m['clients']} clients alors qu'il y en a d'habitude "
                f"~{m['mediane']:.0f} vers {m['heure']} h",
            )

    # Étape 7 : un site dont TOUTES les bornes sont muettes -> une seule alerte pour le site.
    bornes_par_site = {}
    for r in resultats:
        bornes_par_site.setdefault(r["site"], []).append(r)
    for site, bornes in bornes_par_site.items():
        if len(bornes) >= 2 and all(r["erreur"] for r in bornes):
            for r in bornes:
                del actives[(r["nom"], "panne")]
            actives[(site, "site_hors_service")] = (
                "critique",
                f"{site} : les {len(bornes)} bornes sont muettes en même temps "
                f"(coupure de courant ou d'Internet sur le site ?)",
            )
    return actives
