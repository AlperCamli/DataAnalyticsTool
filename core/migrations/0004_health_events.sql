-- Health events: dead-letters, validation rejections, exclusions — the
-- feed the dashboard's Connections/KB Health modules read later. Error
-- detail is stored as delivered (runners scrub resolved secrets, §7).

CREATE TABLE health_events (
    event_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    kind       text NOT NULL,
    severity   text NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'error')),
    system     text,
    job_id     text,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX health_events_by_time ON health_events (created_at DESC);
CREATE INDEX health_events_by_job ON health_events (job_id) WHERE job_id IS NOT NULL;
