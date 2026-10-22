-- Add durable replay protection for production LTI 1.3 launch tokens.
CREATE TABLE IF NOT EXISTS lti_nonce_uses (
    nonce VARCHAR(255) PRIMARY KEY,
    token_sha256 VARCHAR(64) NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
