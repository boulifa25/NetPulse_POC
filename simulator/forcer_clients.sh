#!/bin/sh
# Force la borne à annoncer un nombre fixe de clients (pour simuler une borne "bizarre").
#   docker exec borne-hotel-03 forcer-clients 2        -> annonce toujours 2 clients
#   docker exec borne-hotel-03 forcer-clients normal   -> retour au comportement normal
case "$1" in
  normal) rm -f /etc/netpulse-force; echo "${NOM_BORNE:-$(hostname)} : comportement normal"; exit 0 ;;
  ''|*[!0-9]*) echo "Usage : forcer-clients <nombre> | forcer-clients normal"; exit 1 ;;
esac
echo "$1" > /etc/netpulse-force
echo "${NOM_BORNE:-$(hostname)} : annonce maintenant $1 clients en permanence"
