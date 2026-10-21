-- Store short-lived server-issued LTI OIDC nonce challenges before the LMS redirect.
-- Only the trusted backend should read or consume these rows.
CREATE TABLE IF NOT EXISTS lti_launch_nonces (
    nonce VARCHAR(255) PRIMARY KEY,
    issued_by VARCHAR(120) NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_lti_launch_nonces_expires_at
    ON lti_launch_nonces (expires_at);

ALTER TABLE lti_launch_nonces ENABLE ROW LEVEL SECURITY;
