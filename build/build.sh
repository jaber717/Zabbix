#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd -P)/lib/common.sh"
validate_rhel_platform || exit 1
detect_release_context || exit 1
RHEL_RELEASE=$RHEL_VERSION_ID

for command in curl createrepo_c modifyrepo_c modulemd-merge gpg rpm rpmkeys sha256sum tar jq; do
  need "$command"
done
sudo -n true || die "passwordless sudo is required for the isolated build context"

RUN_ID=${RUN_ID:-"build$(date -u +%Y%m%dT%H%M%SZ)"}
OUTPUT_DIR=${OUTPUT_DIR:-"$PROJECT_ROOT/build/out/$RUN_ID"}
UPDATE_LOCK=${UPDATE_LOCK:-0}
LOCK_MODE=${LOCK_MODE:-frozen}
[[ $LOCK_MODE == frozen || $LOCK_MODE == resolve ]] || die "LOCK_MODE must be frozen or resolve"
[[ $UPDATE_LOCK == 0 ]] || die "tracked historical lock is immutable; retain the generated candidate outside Git"
BUILD_GIT_COMMIT=${BUILD_GIT_COMMIT:-UNKNOWN}
BUILD_GIT_DIRTY=${BUILD_GIT_DIRTY:-UNKNOWN}
git_cmd=(git -c "safe.directory=$PROJECT_ROOT" -C "$PROJECT_ROOT")
actual_commit=$("${git_cmd[@]}" rev-parse --verify HEAD)
[[ -z $("${git_cmd[@]}" status --porcelain) ]] || die "build requires a clean Git working tree"
[[ $BUILD_GIT_COMMIT == UNKNOWN || $BUILD_GIT_COMMIT == "$actual_commit" ]] || die "build commit does not match source HEAD"
BUILD_GIT_COMMIT=$actual_commit
BUILD_GIT_DIRTY=false
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(date -u +%s)}

[[ ! -e "$OUTPUT_DIR" ]] || die "output directory already exists: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/evidence" "$OUTPUT_DIR/work/downloaded" "$OUTPUT_DIR/dist"
exec > >(tee "$OUTPUT_DIR/evidence/build.log") 2>&1

BUILD_ROOT="/var/lib/zabbix-offline-build/m1-${RUN_ID}-$$"
CLEAN_ROOT="$BUILD_ROOT/source-root"
LOCAL_ROOT="$BUILD_ROOT/local-root"
PROXY_PGSQL_ROOT="$BUILD_ROOT/proxy-pgsql-root"
PROXY_SQLITE_ROOT="$BUILD_ROOT/proxy-sqlite-root"
SIGDB="$BUILD_ROOT/signature-root/var/lib/rpm"
cleanup() { safe_remove_root "$BUILD_ROOT"; }
trap cleanup EXIT INT TERM

sudo -n install -d -m 0755 \
  "$CLEAN_ROOT/var/lib/rpm" "$LOCAL_ROOT/var/lib/rpm" "$SIGDB"
sudo -n rpm --root "$CLEAN_ROOT" --initdb

PRE_RPM_HASH=$(host_rpm_hash)
PRE_MODULE_HASH=$(host_module_hash)
log "run=$RUN_ID output=$OUTPUT_DIR clean_root=$CLEAN_ROOT"
log "pre_host_rpm_hash=$PRE_RPM_HASH pre_host_module_hash=$PRE_MODULE_HASH"

[[ $(getenforce) == Enforcing ]] || die "SELinux is not Enforcing"

KEY_DIR="$OUTPUT_DIR/work/keys"
mkdir -p "$KEY_DIR"
curl --fail --silent --show-error --location --max-time 60 \
  --output "$KEY_DIR/RPM-GPG-KEY-ZABBIX-B5333005" "$ZABBIX_KEY_URL"
curl --fail --silent --show-error --location --max-time 60 \
  --output "$KEY_DIR/RPM-GPG-KEY-ZABBIX-08EFA7DD" "$NON_SUPPORTED_KEY_URL"
cp /etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release "$KEY_DIR/RPM-GPG-KEY-redhat-release"
ACTUAL_ZABBIX_FPR=$(gpg --batch --with-colons --show-keys "$KEY_DIR/RPM-GPG-KEY-ZABBIX-B5333005" | awk -F: '$1=="fpr" {print $10; exit}')
[[ "$ACTUAL_ZABBIX_FPR" == "$ZABBIX_KEY_FINGERPRINT" ]] || die "Zabbix key fingerprint mismatch"
ACTUAL_NON_SUPPORTED_FPR=$(gpg --batch --with-colons --show-keys "$KEY_DIR/RPM-GPG-KEY-ZABBIX-08EFA7DD" | awk -F: '$1=="fpr" {print $10; exit}')
[[ "$ACTUAL_NON_SUPPORTED_FPR" == "$NON_SUPPORTED_KEY_FINGERPRINT" ]] || die "Zabbix non-supported key fingerprint mismatch"
{
  echo "ZABBIX_EXPECTED=$ZABBIX_KEY_FINGERPRINT"
  echo "ZABBIX_ACTUAL=$ACTUAL_ZABBIX_FPR"
  gpg --batch --show-keys --with-fingerprint "$KEY_DIR/RPM-GPG-KEY-ZABBIX-B5333005"
  echo "NON_SUPPORTED_EXPECTED=$NON_SUPPORTED_KEY_FINGERPRINT"
  echo "NON_SUPPORTED_ACTUAL=$ACTUAL_NON_SUPPORTED_FPR"
  gpg --batch --show-keys --with-fingerprint "$KEY_DIR/RPM-GPG-KEY-ZABBIX-08EFA7DD"
  gpg --batch --show-keys --with-fingerprint "$KEY_DIR/RPM-GPG-KEY-redhat-release"
} > "$OUTPUT_DIR/evidence/key-fingerprints.txt" 2>&1

log "refreshing metadata in empty source installroot"
source_dnf makecache --refresh
source_dnf repolist --enabled > "$OUTPUT_DIR/evidence/source-repolist.txt" 2>&1
assert_source_repos "$OUTPUT_DIR/evidence/source-repolist.txt"
fping_source_dnf -q repoquery --available --qf '%{name}|%{name}-%{epoch}:%{version}-%{release}.%{arch}|%{repoid}' '*' \
  | grep -E '^[[:alnum:]_.+-]+\|' > "$OUTPUT_DIR/evidence/non-supported-content.txt"
[[ $(wc -l < "$OUTPUT_DIR/evidence/non-supported-content.txt") -eq 1 ]] || die "non-supported repository exposed more than one permitted package"
grep -Fxq "fping|$FPING_NEVRA|$NON_SUPPORTED_REPO" "$OUTPUT_DIR/evidence/non-supported-content.txt" || die "non-supported repository content policy mismatch"

log "selecting target streams inside disposable source root"
source_dnf module enable -y \
  "postgresql:$POSTGRESQL_STREAM" "php:$PHP_STREAM" "nginx:$NGINX_STREAM"
for module in postgresql php nginx; do
  source_dnf module list "$module" > "$OUTPUT_DIR/evidence/source-module-$module.txt" 2>&1
done
grep -Eq "postgresql[[:space:]]+$POSTGRESQL_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/source-module-postgresql.txt" || die "PostgreSQL stream absent"
grep -Eq "php[[:space:]]+$PHP_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/source-module-php.txt" || die "PHP stream absent"
grep -Eq "nginx[[:space:]]+$NGINX_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/source-module-nginx.txt" || die "nginx stream absent"

mapfile -t ZABBIX_SPECS < <(zabbix_specs)
TARGETS=("${ZABBIX_SPECS[@]}" "fping-$FPING_VERSION-$FPING_RELEASE.$FPING_ARCH" "${RUNTIME_PACKAGES[@]}" "${PYTHON_PACKAGES[@]}")
printf '%s\n' "${TARGETS[@]}" > "$OUTPUT_DIR/evidence/target-packages.txt"

log "downloading complete runtime closure with --resolve --alldeps"
source_dnf download --resolve --alldeps --arch=x86_64,noarch \
  --exclude=zabbix-web-mysql --exclude=zabbix-proxy-mysql \
  --destdir="$OUTPUT_DIR/work/downloaded" "${TARGETS[@]}"

mapfile -t RPM_FILES < <(find "$OUTPUT_DIR/work/downloaded" -maxdepth 1 -type f -name '*.rpm' -print | LC_ALL=C sort)
((${#RPM_FILES[@]} > 0)) || die "no RPMs downloaded"
# Do not label newer/older BaseOS content as the host minor. Repository access
# alone does not prove that the administrator's selected content matches it.
content_release=$(rpm -qp --qf '%{NAME}|%{VERSION}\n' "${RPM_FILES[@]}" 2>/dev/null | awk -F'|' '$1=="redhat-release" {print $2}')
[[ $content_release == "$RHEL_VERSION_ID" ]] || die "selected BaseOS content release ${content_release:-missing} differs from host $RHEL_VERSION_ID; review authorized repository content (no release setting was changed)"
if printf '%s\n' "${RPM_FILES[@]}" | grep -Eq '\.(i686|src)\.rpm$'; then
  die "non-target i686/source RPM entered runtime closure"
fi

for package in "${ZABBIX_PACKAGES[@]}"; do
  count=$(rpm -qp --qf '%{NAME}\n' "${RPM_FILES[@]}" 2>/dev/null | grep -cx "$package" || true)
  [[ "$count" == 1 ]] || die "expected exactly one payload for $package, found $count"
done
fping_count=$(rpm -qp --qf '%{NAME}\n' "${RPM_FILES[@]}" 2>/dev/null | grep -cx fping || true)
[[ "$fping_count" == 1 ]] || die "expected exactly one fping payload, found $fping_count"
if rpm -qp --qf '%{NAME}\n' "${RPM_FILES[@]}" 2>/dev/null | grep -Eq '^zabbix-(web|proxy)-mysql$'; then
  die "MySQL Zabbix variant entered the PostgreSQL-only closure"
fi

LOCK_CANDIDATE="$OUTPUT_DIR/rpm-lockfile.candidate.txt"
printf 'NEVRA\tARCH\tREPO_ID\tSHA256\n' > "$LOCK_CANDIDATE"
for rpm_file in "${RPM_FILES[@]}"; do
  IFS='|' read -r name nevra arch < <(rpm -qp --qf '%{NAME}|%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}|%{ARCH}\n' "$rpm_file")
  query=$(source_dnf -q repoquery --available --qf '%{repoid}' "$nevra" 2>/dev/null | grep -E "^($BASEOS_REPO|$APPSTREAM_REPO|$ZABBIX_REPO|$NON_SUPPORTED_REPO)$" | LC_ALL=C sort -u || true)
  if [[ "$name" == fping ]]; then
    [[ "$nevra" == "$FPING_NEVRA" ]] || die "unexpected fping NEVRA: $nevra"
    grep -qx "$NON_SUPPORTED_REPO" <<< "$query" || die "fping non-supported provenance missing"
    repo=$NON_SUPPORTED_REPO
  elif [[ "$name" == zabbix-* ]]; then
    grep -qx "$ZABBIX_REPO" <<< "$query" || die "Zabbix provenance missing for $nevra"
    repo=$ZABBIX_REPO
  elif grep -qx "$BASEOS_REPO" <<< "$query"; then
    repo=$BASEOS_REPO
  elif grep -qx "$APPSTREAM_REPO" <<< "$query"; then
    repo=$APPSTREAM_REPO
  else
    die "approved provenance missing for $nevra"
  fi
  rpm_sha=$(sha256sum "$rpm_file" | awk '{print $1}')
  if [[ "$repo" == "$NON_SUPPORTED_REPO" ]]; then
    [[ "$name" == fping && "$rpm_sha" == "$FPING_SHA256" ]] || die "non-supported repository policy violation for $nevra"
  fi
  printf '%s\t%s\t%s\t%s\n' "$nevra" "$arch" "$repo" "$rpm_sha" >> "$LOCK_CANDIDATE"
done
{ head -n1 "$LOCK_CANDIDATE"; tail -n +2 "$LOCK_CANDIDATE" | LC_ALL=C sort -u; } > "$LOCK_CANDIDATE.sorted"
mv "$LOCK_CANDIDATE.sorted" "$LOCK_CANDIDATE"
assert_lock_source_policy "$LOCK_CANDIDATE"

if [[ "$LOCK_MODE" == frozen ]]; then
  [[ -f "$PROJECT_ROOT/manifests/rpm-lockfile.txt" ]] || die "historical RPM lock absent; restore it from Git or use approved resolve staging"
  cmp -s "$PROJECT_ROOT/manifests/rpm-lockfile.txt" "$LOCK_CANDIDATE" || die "RPM lock drift detected"
fi
# In resolve mode application versions and streams remain pinned by the
# compatibility profile; the new exact dependency lock belongs to this build.

MODULE_DIR="$OUTPUT_DIR/work/module-metadata"
mkdir -p "$MODULE_DIR"
UPSTREAM_MODULEMD=$(sudo -n find "$CLEAN_ROOT/var/cache/dnf" -type f -path "*$APPSTREAM_REPO*" -name '*modules.yaml.gz' -print | head -n1)
[[ -n "$UPSTREAM_MODULEMD" ]] || die "upstream AppStream module metadata not found"
sudo -n cp "$UPSTREAM_MODULEMD" "$MODULE_DIR/upstream-modules.yaml.gz"
sudo -n chown "$(id -u):$(id -g)" "$MODULE_DIR/upstream-modules.yaml.gz"
python3 "$PROJECT_ROOT/build/lib/filter_modulemd.py" \
  "$MODULE_DIR/upstream-modules.yaml.gz" "$MODULE_DIR/selected-modules.yaml" \
  | tee "$OUTPUT_DIR/evidence/module-filter.txt"
modulemd-merge "$MODULE_DIR/selected-modules.yaml" "$MODULE_DIR/validated-modules.yaml"
(cd "$MODULE_DIR" && sha256sum upstream-modules.yaml.gz selected-modules.yaml validated-modules.yaml) \
  > "$OUTPUT_DIR/evidence/module-metadata-sha256.txt"

REPO_DIR="$OUTPUT_DIR/repository"
mkdir -p "$REPO_DIR/rpm" "$REPO_DIR/gpg"
cp "${RPM_FILES[@]}" "$REPO_DIR/rpm/"
cp "$KEY_DIR"/* "$REPO_DIR/gpg/"
touch -d "@$SOURCE_DATE_EPOCH" "$REPO_DIR"/rpm/*.rpm
createrepo_c --revision="$SOURCE_DATE_EPOCH" --set-timestamp-to-revision "$REPO_DIR"
modifyrepo_c --mdtype=modules "$MODULE_DIR/validated-modules.yaml" "$REPO_DIR/repodata"
python3 "$PROJECT_ROOT/build/lib/normalize_repomd_timestamp.py" \
  "$REPO_DIR/repodata/repomd.xml" "$SOURCE_DATE_EPOCH"
touch -d "@$SOURCE_DATE_EPOCH" "$REPO_DIR"/repodata/*

sudo -n rpm --dbpath="$SIGDB" --initdb
sudo -n rpm --dbpath="$SIGDB" --import "$KEY_DIR/RPM-GPG-KEY-redhat-release"
sudo -n rpm --dbpath="$SIGDB" --import "$KEY_DIR/RPM-GPG-KEY-ZABBIX-B5333005"
sudo -n rpm --dbpath="$SIGDB" --import "$KEY_DIR/RPM-GPG-KEY-ZABBIX-08EFA7DD"
: > "$OUTPUT_DIR/evidence/rpm-signatures.txt"
for rpm_file in "$REPO_DIR"/rpm/*.rpm; do
  signature=$(sudo -n rpmkeys --dbpath="$SIGDB" --checksig --verbose "$rpm_file" 2>&1) || {
    printf '%s\n%s\n' "$rpm_file" "$signature" >> "$OUTPUT_DIR/evidence/rpm-signatures.txt"
    die "RPM signature verification failed: $(basename "$rpm_file")"
  }
  printf '%s\n%s\n' "$rpm_file" "$signature" >> "$OUTPUT_DIR/evidence/rpm-signatures.txt"
  if [[ $(basename "$rpm_file") == zabbix-* ]] && ! grep -Eqi 'key ID b5333005: OK' <<< "$signature"; then
    die "Zabbix RPM was not verified by expected key: $(basename "$rpm_file")"
  fi
  if [[ $(basename "$rpm_file") == fping-* ]] && ! grep -Eqi 'key ID 08efa7dd: OK' <<< "$signature"; then
    die "fping RPM was not verified by expected key: $(basename "$rpm_file")"
  fi
done

SQL_RPM=$(find "$REPO_DIR/rpm" -name "zabbix-sql-scripts-$ZABBIX_VERSION-$ZABBIX_RELEASE.noarch.rpm" -print -quit)
[[ -n "$SQL_RPM" ]] || die "SQL scripts RPM missing"
rpm -qlp "$SQL_RPM" > "$OUTPUT_DIR/evidence/sql-package-paths.txt"
for key in postgresql_server postgresql_proxy sqlite_proxy; do
  expected=$(python3 "$PROJECT_ROOT/build/lib/profile.py" get "$PROFILE_PATH" "zabbix.sql_paths.$key")
  grep -Fxq "$expected" "$OUTPUT_DIR/evidence/sql-package-paths.txt" || die "verified SQL path absent: $expected"
done

cat > "$REPO_DIR/zabbix-offline.repo" <<'EOF'
[zabbix-offline]
name=Zabbix RHEL 9 controlled offline repository
baseurl=file:///opt/zabbix-offline/repository
enabled=1
gpgcheck=1
repo_gpgcheck=0
gpgkey=file:///opt/zabbix-offline/repository/gpg/RPM-GPG-KEY-redhat-release
       file:///opt/zabbix-offline/repository/gpg/RPM-GPG-KEY-ZABBIX-B5333005
       file:///opt/zabbix-offline/repository/gpg/RPM-GPG-KEY-ZABBIX-08EFA7DD
EOF

log "testing repository with local content only"
sudo -n rpm --root "$LOCAL_ROOT" --initdb
local_dnf "$LOCAL_ROOT" "$REPO_DIR" makecache --refresh > "$OUTPUT_DIR/evidence/local-makecache.txt" 2>&1
local_dnf "$LOCAL_ROOT" "$REPO_DIR" repolist --enabled > "$OUTPUT_DIR/evidence/local-repolist.txt" 2>&1
grep -q m1-local "$OUTPUT_DIR/evidence/local-repolist.txt" || die "local repository absent"
if grep -Eqi 'netbox-offline|cdn.redhat.com|repo.zabbix.com|https?://' "$OUTPUT_DIR/evidence/local-repolist.txt"; then
  die "online or unrelated source visible during local-only test"
fi
for module in postgresql php nginx; do
  local_dnf "$LOCAL_ROOT" "$REPO_DIR" module list "$module" > "$OUTPUT_DIR/evidence/local-module-$module.txt" 2>&1
done
grep -Eq "postgresql[[:space:]]+$POSTGRESQL_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/local-module-postgresql.txt" || die "local PostgreSQL stream absent"
grep -Eq "php[[:space:]]+$PHP_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/local-module-php.txt" || die "local PHP stream absent"
grep -Eq "nginx[[:space:]]+$NGINX_STREAM([[:space:]]|$)" "$OUTPUT_DIR/evidence/local-module-nginx.txt" || die "local nginx stream absent"
local_dnf "$LOCAL_ROOT" "$REPO_DIR" module enable -y \
  "postgresql:$POSTGRESQL_STREAM" "php:$PHP_STREAM" "nginx:$NGINX_STREAM" \
  > "$OUTPUT_DIR/evidence/local-module-enable.txt" 2>&1
LOCAL_INSTALL_TARGETS=()
for target in "${TARGETS[@]}"; do
  case "$target" in
    zabbix-proxy-pgsql-*|zabbix-proxy-sqlite3-*) ;;
    *) LOCAL_INSTALL_TARGETS+=("$target") ;;
  esac
done
local_dnf "$LOCAL_ROOT" "$REPO_DIR" install -y "${LOCAL_INSTALL_TARGETS[@]}" \
  > "$OUTPUT_DIR/evidence/local-install.txt" 2>&1
sudo -n rpm --root "$LOCAL_ROOT" -qa --qf '%{NAME}|%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' \
  | LC_ALL=C sort > "$OUTPUT_DIR/evidence/local-installed-packages.txt"

for proxy_spec in \
  "zabbix-proxy-pgsql-$ZABBIX_VERSION-$ZABBIX_RELEASE" \
  "zabbix-proxy-sqlite3-$ZABBIX_VERSION-$ZABBIX_RELEASE"; do
  case "$proxy_spec" in
    zabbix-proxy-pgsql-*) proxy_root=$PROXY_PGSQL_ROOT; proxy_label=pgsql ;;
    zabbix-proxy-sqlite3-*) proxy_root=$PROXY_SQLITE_ROOT; proxy_label=sqlite3 ;;
  esac
  sudo -n install -d -m 0755 "$proxy_root/var/lib/rpm"
  sudo -n rpm --root "$proxy_root" --initdb
  local_dnf "$proxy_root" "$REPO_DIR" makecache --refresh \
    > "$OUTPUT_DIR/evidence/local-proxy-$proxy_label-makecache.txt" 2>&1
  local_dnf "$proxy_root" "$REPO_DIR" install -y "$proxy_spec" \
    > "$OUTPUT_DIR/evidence/local-proxy-$proxy_label-install.txt" 2>&1
  sudo -n rpm --root "$proxy_root" -q "$proxy_spec" \
    > "$OUTPUT_DIR/evidence/local-proxy-$proxy_label-query.txt" 2>&1
done

POST_RPM_HASH=$(host_rpm_hash)
POST_MODULE_HASH=$(host_module_hash)
[[ "$POST_RPM_HASH" == "$PRE_RPM_HASH" ]] || die "host RPM database changed during pipeline"
[[ "$POST_MODULE_HASH" == "$PRE_MODULE_HASH" ]] || die "host module state changed during pipeline"

"$PROJECT_ROOT/build/build-wheels.sh" "$OUTPUT_DIR/wheelhouse" | tee "$OUTPUT_DIR/evidence/wheel-pipeline.txt"

RELEASE_TREE="$OUTPUT_DIR/release-tree"
mkdir -p "$RELEASE_TREE"/{compat,docs,integration/wheels}
cp -a "$REPO_DIR" "$RELEASE_TREE/repository"
cp "$PROFILE_PATH" "$RELEASE_TREE/compat/zabbix-7.0.yaml"
python3 - "$RELEASE_TREE/compat/zabbix-7.0.yaml" "$RHEL_RELEASE" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
profile = json.loads(path.read_text())
profile['target']['release'] = sys.argv[2]
path.write_text(json.dumps(profile, indent=2) + '\n')
PY
cp "$PROJECT_ROOT/integrations/netbox-zabbix-sync/wheels/requirements.in" "$PROJECT_ROOT/integrations/netbox-zabbix-sync/wheels/requirements.lock" "$PROJECT_ROOT/integrations/netbox-zabbix-sync/wheels/README.md" "$RELEASE_TREE/integration/wheels/"
cp -a "$OUTPUT_DIR/wheelhouse/." "$RELEASE_TREE/integration/wheels/"
cp "$PROJECT_ROOT/docs/OFFLINE-INSTALL.md" "$PROJECT_ROOT/docs/ARCHITECTURE.md" "$PROJECT_ROOT/docs/DECISIONS.md" "$RELEASE_TREE/docs/"
cp "$LOCK_CANDIDATE" "$RELEASE_TREE/rpm-lockfile.txt"
cp "$LOCK_CANDIDATE" "$RELEASE_TREE/RPM-MANIFEST.txt"

RPM_COUNT=${#RPM_FILES[@]}
WHEEL_COUNT=$(find "$RELEASE_TREE/integration/wheels" -maxdepth 1 -type f -name '*.whl' | wc -l)
BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
jq -n \
  --arg release "$RELEASE_NAME-$RELEASE_VERSION-build$RELEASE_BUILD" \
  --arg designation "Zabbix RHEL $RHEL_RELEASE offline deployment bundle" \
  --arg timestamp "$BUILD_TIMESTAMP" \
  --arg git_commit "$BUILD_GIT_COMMIT" --arg git_dirty "$BUILD_GIT_DIRTY" \
  --arg host "$(hostname -f)" --arg rhel "$RHEL_RELEASE" --arg arch "$TARGET_ARCH" \
  --arg effective_release "$DNF_EFFECTIVE_RELEASE" --arg explicit_pin "$RHEL_EXPLICIT_PIN" \
  --arg zabbix "$ZABBIX_VERSION-$ZABBIX_RELEASE" --arg postgresql "$POSTGRESQL_STREAM" \
  --arg php "$PHP_STREAM" --arg nginx "$NGINX_STREAM" --arg python "$PYTHON_ABI" \
  --arg modulemd_sha "$(sha256sum "$MODULE_DIR/upstream-modules.yaml.gz" | awk '{print $1}')" \
  --arg local_repomd_sha "$(sha256sum "$REPO_DIR/repodata/repomd.xml" | awk '{print $1}')" \
  --argjson rpm_count "$RPM_COUNT" --argjson wheel_count "$WHEEL_COUNT" \
  --argjson repos "$(printf '%s\n' "$BASEOS_REPO" "$APPSTREAM_REPO" "$ZABBIX_REPO" "$NON_SUPPORTED_REPO" | jq -R . | jq -s .)" \
  '{release:$release,designation:$designation,build_timestamp_utc:$timestamp,git:{commit:$git_commit,dirty:$git_dirty},build_host:$host,target:{rhel_release:$rhel,arch:$arch},repository_context:{effective_release:$effective_release,explicit_pin:$explicit_pin},zabbix:$zabbix,streams:{postgresql:$postgresql,php:$php,nginx:$nginx},python:{abi:$python,status:"standard-library integration; no third-party wheels"},source_repository_ids:$repos,metadata:{upstream_appstream_modulemd_sha256:$modulemd_sha,local_repomd_sha256:$local_repomd_sha},rpm_count:$rpm_count,wheel_count:$wheel_count,artifact_sha256:null}' \
  > "$RELEASE_TREE/BUILD-INFO.json"

touch "$RELEASE_TREE/MANIFEST.txt" "$RELEASE_TREE/SHA256SUMS"
(cd "$RELEASE_TREE" && find . -type f -printf '%P\n' | LC_ALL=C sort) > "$OUTPUT_DIR/work/manifest.generated"
cp "$OUTPUT_DIR/work/manifest.generated" "$RELEASE_TREE/MANIFEST.txt"
(cd "$RELEASE_TREE" && find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) > "$RELEASE_TREE/SHA256SUMS"

"$PROJECT_ROOT/build/verify-build.sh" "$RELEASE_TREE" "$LOCK_CANDIDATE" \
  | tee "$OUTPUT_DIR/evidence/release-verification.txt"

ARTIFACT="$OUTPUT_DIR/dist/$RELEASE_NAME-$RELEASE_VERSION-build$RELEASE_BUILD.tar.gz"
tar --sort=name --mtime="@$SOURCE_DATE_EPOCH" --owner=0 --group=0 --numeric-owner \
  -C "$RELEASE_TREE" -czf "$ARTIFACT" .
ARTIFACT_SHA=$(sha256sum "$ARTIFACT" | awk '{print $1}')
printf '%s  %s\n' "$ARTIFACT_SHA" "$(basename "$ARTIFACT")" > "$ARTIFACT.sha256"
cp "$RELEASE_TREE"/{SHA256SUMS,MANIFEST.txt,RPM-MANIFEST.txt,BUILD-INFO.json} "$OUTPUT_DIR/dist/"

sudo -n chown -R "$(id -u):$(id -g)" "$OUTPUT_DIR"
{
  echo "RUN_ID=$RUN_ID"
  echo "RPM_COUNT=$RPM_COUNT"
  echo "WHEEL_COUNT=$WHEEL_COUNT"
  echo "PRE_HOST_RPM_SHA256=$PRE_RPM_HASH"
  echo "POST_HOST_RPM_SHA256=$POST_RPM_HASH"
  echo "PRE_HOST_MODULE_SHA256=$PRE_MODULE_HASH"
  echo "POST_HOST_MODULE_SHA256=$POST_MODULE_HASH"
  echo "ARTIFACT=$(basename "$ARTIFACT")"
  echo "ARTIFACT_SHA256=$ARTIFACT_SHA"
  echo "ARTIFACT_BYTES=$(stat -c %s "$ARTIFACT")"
  echo "RESULT=PASS"
} | tee "$OUTPUT_DIR/build-result.txt"
