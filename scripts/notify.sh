#!/usr/bin/env bash
set -euo pipefail

# Script: notify.sh
# Description: Send a push notification to the agentic-trading ntfy topic.
# Author: Doug Morand
# Date: 2026-06-15

DEPENDENCIES=(curl)
SCRIPT_NAME=$(basename "$0")

# ntfy server and topic are overridable for self-hosted setups.
NTFY_SERVER="${NTFY_SERVER:-https://ntfy.sh}"
NTFY_TOPIC="${NTFY_TOPIC:-agentic-trading}"

log_info()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO  $*"; }
log_error() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR $*" >&2; }

function usage() {
    cat <<EOF

Send a push notification to the ${NTFY_TOPIC} ntfy topic.

Usage: ${SCRIPT_NAME} [OPTIONS] <message>

Options:
    -t, --title    <text>   Notification title
    -p, --priority <1-5>    Priority (1=min, 3=default, 5=max)
    -T, --tags     <csv>    Comma-separated tags/emoji (e.g. "warning,skull")
    -h, --help              Show this help message

Environment:
    NTFY_TOKEN    Bearer token for authentication (required)
    NTFY_SERVER   ntfy server URL (default: https://ntfy.sh)
    NTFY_TOPIC    ntfy topic to publish to (default: agentic-trading)

Dependencies: ${DEPENDENCIES[*]}

Examples:
    ${SCRIPT_NAME} "Trade executed: bought 10 SPY"
    ${SCRIPT_NAME} -t "Stop hit" -p 5 -T "warning" "AAPL stopped out at -8%"

EOF
    exit 0
}

function main() {
    local title=""
    local priority=""
    local tags=""
    local message=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
        -t | --title)    title="$2";    shift 2 ;;
        -p | --priority) priority="$2"; shift 2 ;;
        -T | --tags)     tags="$2";     shift 2 ;;
        -h | --help) usage ;;
        -*)
            log_error "Unknown option: $1"
            usage
            ;;
        *) message="$1"; shift ;;
        esac
    done

    [[ -z "$message" ]] && log_error "a message is required" && usage
    [[ -z "${NTFY_TOKEN:-}" ]] && log_error "NTFY_TOKEN is not set" && exit 1

    exit_on_missing_tools "${DEPENDENCIES[@]}"

    send_notification "$message" "$title" "$priority" "$tags"
}

function send_notification() {
    local message="$1"
    local title="$2"
    local priority="$3"
    local tags="$4"

    local -a headers=(-H "Authorization: Bearer ${NTFY_TOKEN}")
    [[ -n "$title" ]]    && headers+=(-H "Title: ${title}")
    [[ -n "$priority" ]] && headers+=(-H "Priority: ${priority}")
    [[ -n "$tags" ]]     && headers+=(-H "Tags: ${tags}")

    if ! curl -fsS "${headers[@]}" -d "$message" "${NTFY_SERVER}/${NTFY_TOPIC}" >/dev/null; then
        log_error "Failed to send notification to ${NTFY_SERVER}/${NTFY_TOPIC}"
        exit 1
    fi

    log_info "Notification sent to ${NTFY_TOPIC}"
}

function exit_on_missing_tools() {
    for cmd in "$@"; do
        if ! command -v "$cmd" &>/dev/null; then
            log_error "Required tool '$cmd' is not installed or not in PATH"
            exit 1
        fi
    done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
    exit 0
fi
