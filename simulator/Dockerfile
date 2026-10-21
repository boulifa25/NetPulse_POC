# Une "fausse borne WiFi" : un petit Linux (Alpine) avec un vrai agent SNMP.
# La même image sert pour toutes les bornes ; chacune reçoit son identité au démarrage.
FROM alpine:3.20

# tzdata : pour que la borne vive à l'heure locale (variable TZ, voir bornes.env)
RUN apk add --no-cache net-snmp tzdata

COPY snmpd.conf /etc/snmp/snmpd.conf.modele
COPY clients_wifi.sh /usr/local/bin/clients_wifi.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY surcharge.sh /usr/local/bin/surcharge
COPY forcer_clients.sh /usr/local/bin/forcer-clients

# Retire les fins de ligne Windows (CRLF) au cas où, puis rend les scripts exécutables
RUN sed -i 's/\r$//' /usr/local/bin/clients_wifi.sh /usr/local/bin/entrypoint.sh \
        /usr/local/bin/surcharge /usr/local/bin/forcer-clients /etc/snmp/snmpd.conf.modele \
    && chmod +x /usr/local/bin/clients_wifi.sh /usr/local/bin/entrypoint.sh \
        /usr/local/bin/surcharge /usr/local/bin/forcer-clients

EXPOSE 161/udp

CMD ["/usr/local/bin/entrypoint.sh"]
