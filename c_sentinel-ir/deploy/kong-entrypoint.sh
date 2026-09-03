#!/bin/sh
# deploy/kong-entrypoint.sh - render gateway/kong.yml with the JWT signing key,
# then hand over to Kong's own entrypoint.
#
# Why this exists. gateway/kong.yml is checked into git, so it cannot contain
# the signing key; the key arrives as $KONG_JWT_SECRET from deploy/.env. Kong
# offers no working way to inject it into a `jwt_secrets.secret` field in DB-less
# mode - `${{ env "..." }}` is decK's templating, not Kong's, and a
# `{vault://env/...}` reference resolves under `kong vault get` but is not
# dereferenced for that field in Kong 3.7. Both fail silently: the gateway
# starts healthy and rejects every valid token with "Invalid signature".
#
# So the substitution happens here, at container start, into a copy under /tmp.
# The mounted config stays read-only and key-free; the rendered copy exists only
# inside the running container's filesystem.
#
# Author: Colile

set -eu

SOURCE_CONFIG=/etc/kong/kong.yml
RENDERED_CONFIG=/tmp/kong.rendered.yml
PLACEHOLDER=__JWT_SECRET__

if [ -z "${KONG_JWT_SECRET:-}" ]; then
    echo "Error: KONG_JWT_SECRET is not set; the gateway cannot validate tokens." >&2
    echo "Description: set JWT_SECRET in deploy/.env" >&2
    exit 1
fi

if ! grep -q "$PLACEHOLDER" "$SOURCE_CONFIG"; then
    echo "Error: $PLACEHOLDER not found in $SOURCE_CONFIG." >&2
    echo "Description: the gateway config no longer has a key placeholder to fill" >&2
    exit 1
fi

# awk rather than sed: the key is a hex string, but awk's literal
# index/substr splice cannot misread a metacharacter in it whatever it contains.
awk -v secret="$KONG_JWT_SECRET" -v placeholder="$PLACEHOLDER" '
{
    position = index($0, placeholder)
    if (position > 0) {
        $0 = substr($0, 1, position - 1) secret substr($0, position + length(placeholder))
    }
    print
}
' "$SOURCE_CONFIG" > "$RENDERED_CONFIG"

chmod 600 "$RENDERED_CONFIG"

export KONG_DECLARATIVE_CONFIG="$RENDERED_CONFIG"
echo "Description: rendered gateway config to $RENDERED_CONFIG"

exec /docker-entrypoint.sh "$@"
