#!/usr/bin/env bash
# Source-only shared platform control. Never source/evaluate os-release as code.
validate_rhel_platform() {
  local os_file=${1:-/etc/os-release} arch=${2:-} key value detected_id='' detected_version=''
  [[ -n $arch ]] || arch=$(uname -m) || return 1
  if [[ ! -r $os_file ]]; then
    printf 'FAIL: cannot read OS identity: %s\n' "$os_file" >&2
    return 1
  fi
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$value" in
      \"*\") value=${value:1:${#value}-2} ;;
      \'*\') value=${value:1:${#value}-2} ;;
    esac
    case "$key" in
      ID) detected_id=$value ;;
      VERSION_ID) detected_version=$value ;;
    esac
  done < "$os_file"
  if [[ $detected_id != rhel || ! $detected_version =~ ^9\.[0-9]+$ || $arch != x86_64 ]]; then
    printf 'FAIL: requires RHEL 9.x x86_64; detected ID=%s VERSION_ID=%s architecture=%s\n' \
      "${detected_id:-missing}" "${detected_version:-missing}" "$arch" >&2
    return 1
  fi
  RHEL_VERSION_ID=$detected_version
  export RHEL_VERSION_ID
}

# Only successful, unambiguous subscription output represents an explicit pin.
parse_release_pin() {
  local status=$1 output=$2
  [[ $status == 0 ]] || return 0
  if [[ $output =~ ^Release:[[:space:]]+([0-9]+\.[0-9]+)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  elif [[ $output =~ ^[0-9]+\.[0-9]+$ ]]; then
    printf '%s\n' "$output"
  fi
}

detect_release_context() {
  local output status=0
  output=$(LC_ALL=C timeout 20 subscription-manager release --show 2>&1) || status=$?
  RHEL_EXPLICIT_PIN=$(parse_release_pin "$status" "$output")
  printf 'SUBSCRIPTION_RELEASE_STATUS=%s\nSUBSCRIPTION_RELEASE_OUTPUT=%s\n' "$status" "$output"
  HOST_RELEASE_ARGS=()
  if [[ -n $RHEL_EXPLICIT_PIN ]]; then
    [[ $RHEL_EXPLICIT_PIN == "$RHEL_VERSION_ID" ]] || {
      printf 'FAIL: administrator release pin %s differs from host %s; operator review required\n' "$RHEL_EXPLICIT_PIN" "$RHEL_VERSION_ID" >&2
      return 1
    }
    HOST_RELEASE_ARGS=("--releasever=$RHEL_EXPLICIT_PIN")
    DNF_EFFECTIVE_RELEASE=$RHEL_EXPLICIT_PIN
  else
    # Empty installroots cannot detect releasever. Inherit the real host DNF
    # substitution (normally major 9), never substitute our own minor version.
    DNF_EFFECTIVE_RELEASE=$(python3 -c 'import dnf; b=dnf.Base(); b.conf.read(); b.conf.substitutions.update_from_etc("/", varsdir=b.conf.varsdir); print(b.conf.substitutions["releasever"])') || return 1
  fi
  [[ $DNF_EFFECTIVE_RELEASE =~ ^9(\.[0-9]+)?$ ]] || {
    printf 'FAIL: unsupported effective DNF release: %s\n' "$DNF_EFFECTIVE_RELEASE" >&2
    return 1
  }
  printf 'EXPLICIT_PIN=%s\nINSTALLROOT_RELEASEVER=%s\n' "${RHEL_EXPLICIT_PIN:-none}" "$DNF_EFFECTIVE_RELEASE"
  export DNF_EFFECTIVE_RELEASE RHEL_EXPLICIT_PIN
}
