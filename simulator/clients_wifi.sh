#!/bin/sh
# Simule le nombre d'appareils connectés à la borne selon l'heure et le type de site,
# plus un peu de hasard. Le profil (hotel, residence, magasin) est écrit par entrypoint.sh.
# La commande "surcharge N" (surcharge.sh) ajoute N clients pour simuler une foule.
# La commande "forcer-clients N" (forcer_clients.sh) impose un nombre fixe de clients.
if [ -f /etc/netpulse-force ]; then cat /etc/netpulse-force; exit 0; fi

PROFIL=$(cat /etc/netpulse-profil 2>/dev/null || echo hotel)
SURPLUS=$(cat /etc/netpulse-surplus 2>/dev/null || echo 0)
HEURE=$(date +%H)
HEURE=${HEURE#0}

case "$PROFIL" in
  residence)
    # Les habitants partent travailler le matin et rentrent le soir.
    if   [ "$HEURE" -lt 7 ];  then BASE=6
    elif [ "$HEURE" -lt 18 ]; then BASE=4
    else BASE=18
    fi ;;
  magasin)
    # Fermé la nuit (presque personne), pic d'affluence l'après-midi.
    if   [ "$HEURE" -lt 9 ] || [ "$HEURE" -ge 20 ]; then echo $(( $(od -An -N1 -tu1 /dev/urandom) % 2 + SURPLUS )); exit 0
    elif [ "$HEURE" -lt 12 ]; then BASE=10
    elif [ "$HEURE" -lt 18 ]; then BASE=22
    else BASE=14
    fi ;;
  *)
    # Hôtel : peu de monde la nuit, beaucoup le soir.
    if   [ "$HEURE" -lt 7 ];  then BASE=2
    elif [ "$HEURE" -lt 12 ]; then BASE=8
    elif [ "$HEURE" -lt 18 ]; then BASE=12
    else BASE=20
    fi ;;
esac

# Hasard tiré de /dev/urandom : srand() se base sur la seconde en cours, donc des
# bornes interrogées en même temps auraient toutes renvoyé le même chiffre.
HASARD=$(( $(od -An -N1 -tu1 /dev/urandom) % 6 ))
echo $((BASE + HASARD + SURPLUS))
