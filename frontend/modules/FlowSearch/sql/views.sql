-- NetOps Flow Search — compatibility layer over Akvorado 2026.10.0 schema.
--
-- Applied by netflow-vm/bin/clickhouse-apply.sh. Safe to rerun.
--
-- Why the compat view: Akvorado's `akvorado.flows` schema is version-managed by
-- the outlet; column names and types can shift between releases. Our UI pins
-- to `netops.flow_v1` so an Akvorado bump never breaks Flow Search; the only
-- change on a bump is this one file.
--
-- SamplingRate semantics: Akvorado stores `Bytes`/`Packets` as the SAMPLED
-- values received from the exporter. The physical traffic estimate is
--   Bytes_estimate = Bytes * if(SamplingRate > 0, SamplingRate, 1)
-- which flow_api.php uses in its peak-bps calculation. Consult the Akvorado
-- documentation for the exact release deployed before changing this contract.
--
-- The ${FLOW_API_RO_PASSWORD} placeholder is substituted at apply time by
-- clickhouse-apply.sh from /etc/flow-api/ch-pass (0600 root:root). This file
-- is NEVER committed with a real password.

CREATE DATABASE IF NOT EXISTS netops;

CREATE OR REPLACE VIEW netops.flow_v1 AS
SELECT
    TimeReceived,
    -- Deterministic flow_id for keyset pagination tie-breaking.
    cityHash64(
        toString(TimeReceived),
        toString(SrcAddr), toString(DstAddr),
        toString(SrcPort), toString(DstPort),
        toString(ExporterAddress),
        toString(coalesce(InIfName, '')),
        toString(coalesce(OutIfName, ''))
    ) AS flow_id,
    SrcAddr,
    DstAddr,
    SrcPort,
    DstPort,
    multiIf(Proto = 1, 'ICMP',
            Proto = 6, 'TCP',
            Proto = 17, 'UDP',
            Proto = 47, 'GRE',
            Proto = 50, 'ESP',
            Proto = 58, 'ICMPv6',
            toString(Proto)) AS Proto,
    Bytes,
    Packets,
    coalesce(SamplingRate, 1) AS SamplingRate,
    Bytes   * if(SamplingRate > 0, SamplingRate, 1) AS BytesEstimated,
    Packets * if(SamplingRate > 0, SamplingRate, 1) AS PacketsEstimated,
    ExporterAddress,
    InIfName,
    OutIfName,
    coalesce(InIfDescription, '')  AS InIfDescription,
    coalesce(OutIfDescription, '') AS OutIfDescription
FROM akvorado.flows;

-- Read-only user used ONLY by the local flow-api gateway (loopback).
CREATE USER IF NOT EXISTS flow_api_ro IDENTIFIED WITH sha256_password BY '${FLOW_API_RO_PASSWORD}';
-- Attach the hard-cap profile from overlay/clickhouse/users.d/zbx-flow-ro-profile.xml.
ALTER USER flow_api_ro SETTINGS PROFILE 'flow_api_ro_profile';

GRANT SELECT ON netops.flow_v1 TO flow_api_ro;
-- Deliberately NO grants on akvorado.* raw tables.

-- Materialised convenience: a one-minute pre-aggregate of sampled bytes.
-- Flow Search's `summary` endpoint uses this for peak_bps when the window is
-- long, to avoid re-aggregating raw flows on every refresh.
CREATE TABLE IF NOT EXISTS netops.flow_bps_1m
(
    bucket DateTime,
    exporter IPv6,
    in_if LowCardinality(String),
    bytes_estimated UInt64
)
ENGINE = SummingMergeTree
PARTITION BY toYYYYMMDD(bucket)
ORDER BY (bucket, exporter, in_if)
TTL bucket + INTERVAL 14 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS netops.flow_bps_1m_mv
TO netops.flow_bps_1m
AS
SELECT
    toStartOfMinute(TimeReceived) AS bucket,
    ExporterAddress AS exporter,
    coalesce(InIfName, '') AS in_if,
    sum(Bytes * if(SamplingRate > 0, SamplingRate, 1)) AS bytes_estimated
FROM akvorado.flows
GROUP BY bucket, exporter, in_if;

GRANT SELECT ON netops.flow_bps_1m TO flow_api_ro;
