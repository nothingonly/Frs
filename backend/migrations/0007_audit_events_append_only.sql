-- POSTGRESQL_ONLY
-- Make audit evidence append-only for the application role. Database superusers may still
-- disable triggers; operational separation and database audit logging remain required.
CREATE OR REPLACE FUNCTION public.reject_audit_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only; % is forbidden', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON public.audit_events;
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON public.audit_events
FOR EACH ROW EXECUTE FUNCTION public.reject_audit_event_mutation();
