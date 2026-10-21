#!/bin/sh
# Simule une foule sur la borne : ajoute N clients au nombre normal.
#   docker exec borne-magasin-01 surcharge 40   -> +40 clients
#   docker exec borne-magasin-01 surcharge 0    -> retour à la normale
SURPLUS=${1:-0}
case "$SURPLUS" in
  ''|*[!0-9]*) echo "Usage : surcharge <nombre de clients en plus, ex. 40 ; 0 pour arrêter>"; exit 1 ;;
esac
echo "$SURPLUS" > /etc/netpulse-surplus
echo "${NOM_BORNE:-$(hostname)} : $SURPLUS clients ajoutés au nombre normal"
