#!/bin/sh
# Reuse the platform's authoritative data-SIM/device mapping. Cache its inputs
# with shell reads; unchanged event notifications must not spawn uci/device.
IFACE=${IFACE:-sipa_eth0}
ndp_iface_refresh() {
    local root=${MU300_NDP_RUN:-/run} lib=${MU300_NDP_SIM_ENV:-/opt/mu300/bin/mu300-sim-env}
    local file=${MU300_NDP_CONFIG:-/etc/config/unisoc_modem} signature= line=
    [ ! -e "$root/mu300/sim-switching" ] && [ ! -e "$root/mu300/sim-active-unknown" ] &&
        [ ! -d "$root/unisoc-data-sim-switch" ] || return 75
    [ -r "$lib" ] || { echo "ndp-learn: SIM mapping library is missing" >&2; return 1; }
    if [ -r "$file" ]; then
        while IFS= read -r line || [ -n "$line" ]; do signature="$signature
$line"; done < "$file"
    fi
    [ "${ndp_iface_signature:-unset}" != "$signature" ] || return 0
    . "$lib" || return 1
    mu300_sim_env "" || return 1
    case "$MU300_SIM_DEVICE" in ''|*[!a-zA-Z0-9_.:-]*) return 1 ;; esac
    [ "${#MU300_SIM_DEVICE}" -le 15 ] || return 1
    IFACE=$MU300_SIM_DEVICE
    ndp_iface_signature=$signature
}
