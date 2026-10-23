#!/bin/sh
# Event waiting adapted from liuwang97/cpu-load ccf89bb6. Route policy remains
# in ndp-learn; monitor our neighbours too, since this branch retains /128 pins.
ndp_events=0 ndp_event_pid= NDP_DIRTY=0 NDP_NOW=0 NDP_FULL_AT=0 NDP_WITHDRAW_AT=0
NDP_INTERVAL=10
ndp_clock() {
    local up rest
    IFS=' ' read -r up rest < /proc/uptime || return 1
    NDP_NOW=${up%.*}
}
ndp_events_stop() {
    if [ -n "$ndp_event_pid" ]; then
        kill "$ndp_event_pid" 2>/dev/null || true
        wait "$ndp_event_pid" 2>/dev/null || true
    fi
    [ "$ndp_events" = 0 ] || exec 8<&-
    ndp_events=0 ndp_event_pid=
}
ndp_events_start() {
    local dir
    ndp_clock || return 1
    dir=$(mktemp -d "${TMPDIR:-/tmp}/ndp-events.XXXXXX") || return 1
    if ! mkfifo -m 600 "$dir/monitor"; then rmdir "$dir"; return 1; fi
    ip -o -6 monitor label address route neigh > "$dir/monitor" 2>/dev/null </dev/null 8<&- &
    ndp_event_pid=$!
    exec 8< "$dir/monitor"
    rm -f "$dir/monitor"; rmdir "$dir"
    ndp_events=1
    NDP_TICK_AT=$((NDP_NOW + NDP_INTERVAL))
}
# Only stable routing fields. Packet/reference counters must not turn ordinary
# traffic into a route change. No helper processes are needed for this snapshot.
ndp_snapshot() {
    local ad ix pl sc fl dev dst dp src sp gw metric refs uses flags rest
    [ -r "$IF_INET6" ] && [ -r "${MU300_IPV6_ROUTE:-/proc/net/ipv6_route}" ] || return 1
    NDP_SNAPSHOT= NDP_GLOBAL=0
    while read -r ad ix pl sc fl dev; do
        case "$dev" in "${IFACE:-sipa_eth0}"|br-lan)
            NDP_SNAPSHOT="$NDP_SNAPSHOT|a:$ad:$ix:$pl:$sc:$fl:$dev" ;;
        esac
        [ "$dev" != "${IFACE:-sipa_eth0}" ] || [ "$sc" != 00 ] || NDP_GLOBAL=1
    done < "$IF_INET6"
    NDP_ADDRESSES=$NDP_SNAPSHOT
    while read -r dst dp src sp gw metric refs uses flags dev rest; do
        case "$dev" in "${IFACE:-sipa_eth0}"|br-lan)
            NDP_SNAPSHOT="$NDP_SNAPSHOT|r:$dst:$dp:$src:$sp:$gw:$metric:$flags:$dev" ;;
        esac
    done < "${MU300_IPV6_ROUTE:-/proc/net/ipv6_route}"
}
ndp_event_relevant() {
    case " $1 " in *'[ADDR]'*|*" ${IFACE:-sipa_eth0} "*|*' br-lan '*) ;; *) return 1 ;; esac
    # A deletion can race our post-write snapshot. Force a pass even then;
    # idempotent replacements do not delete routes on subsequent passes.
    case "$1" in *'[NEIGH]'*|*Deleted*) NDP_DIRTY=1 ;; esac
    return 0
}
ndp_events_wait() {
    local due line status
    NDP_DIRTY=0
    ndp_clock || return 1
    due=$NDP_TICK_AT
    [ "$NDP_FULL_AT" -ge "$due" ] || due=$NDP_FULL_AT
    while [ "$NDP_NOW" -lt "$due" ]; do
        status=0
        IFS= read -r -t "$((due - NDP_NOW))" line <&8 || status=$?
        ndp_clock || return 1
        if [ "$status" != 0 ]; then
            # Bash timeout is not EOF, even if uptime rounds below due.
            [ "$status" != 142 ] || continue
            # A dead monitor is a failed service, not permission to silently
            # start a different observer implementation.
            [ "$NDP_NOW" -ge "$due" ] || { echo "ndp-learn: route monitor disconnected" >&2; return 1; }
            break
        fi
        ndp_event_relevant "$line" && return 0
    done
    if [ "$NDP_NOW" -ge "$NDP_TICK_AT" ]; then NDP_TICK_AT=$((NDP_NOW + NDP_INTERVAL)); fi
    return 0
}
