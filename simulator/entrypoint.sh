#!/bin/sh
# Donne son identité à la borne (variables NOM_BORNE et EMPLACEMENT du docker-compose),
# puis démarre l'agent SNMP.
NOM_BORNE=${NOM_BORNE:-borne-inconnue}
EMPLACEMENT=${EMPLACEMENT:-Emplacement inconnu}

sed -e "s|__NOM__|$NOM_BORNE|" -e "s|__EMPLACEMENT__|$EMPLACEMENT|" \
    /etc/snmp/snmpd.conf.modele > /etc/snmp/snmpd.conf

# Rythme de fréquentation (hotel, residence, magasin), lu par clients_wifi.sh
echo "${PROFIL:-hotel}" > /etc/netpulse-profil

# -f : reste au premier plan (obligatoire dans Docker) ; -Lo : logs dans la console
# -C : ignore les fichiers de config par défaut (sinon snmpd.conf est lu deux fois
#      et l'agent plante : port 161 déjà pris, "extend" en double)
exec snmpd -f -Lo -C -c /etc/snmp/snmpd.conf
