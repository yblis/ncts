#!/bin/sh
set -eu

DATA_DIR=/opt/ulix-ncts/data

case "${ULIX_REQUIRE_SMB:-1}" in
    1|true|TRUE|oui|OUI)
        smb_monte=0
        while read -r source cible type options reste; do
            if [ "$cible" = "$DATA_DIR" ] && [ "$type" = "cifs" ]; then
                smb_monte=1
                break
            fi
        done < /proc/mounts
        if [ "$smb_monte" -ne 1 ]; then
            echo "ERREUR : $DATA_DIR n'est pas monté depuis un partage SMB/CIFS." >&2
            echo "Monter le partage SMB sur l'hôte Linux avant de démarrer le service." >&2
            exit 78
        fi
        ;;
esac

exec python /opt/ulix-ncts/app_ncts/lancer.py "$@"
