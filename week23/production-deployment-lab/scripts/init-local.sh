#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
umask 077
mkdir -p secrets .local

if [ ! -s secrets/postgres_password ]; then
    if [ -n "${POSTGRES_PASSWORD:-}" ]; then
        printf '%s' "$POSTGRES_PASSWORD" > secrets/postgres_password
    else
        python3 -c 'import secrets; print(secrets.token_urlsafe(36), end="")' > secrets/postgres_password
    fi
fi
chmod 600 secrets/postgres_password

if [ ! -s secrets/local-tls.key ] || [ ! -s secrets/local-tls.crt ]; then
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 30 \
        -keyout secrets/local-tls.key -out secrets/local-tls.crt \
        -subj '/CN=localhost' \
        -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
        -addext 'keyUsage=digitalSignature,keyEncipherment' \
        -addext 'extendedKeyUsage=serverAuth'
fi
chmod 600 secrets/local-tls.key secrets/local-tls.crt

printf 'LOCAL_UID=%s\nLOCAL_GID=%s\n' "$(id -u)" "$(id -g)" > .env
chmod 600 .env
printf 'Local password and TLS material are ready under ignored secrets/.\n'
