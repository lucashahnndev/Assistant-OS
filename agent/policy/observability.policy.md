# Observability Policy

- every endpoint should carry a unique request ID for traceability;
- every error should include full stack trace and enough context to debug the failure;
- logs should be structured as JSON, not free-form text;
- every service should expose health checks with useful status detail;
- database access should be logged with timing and enough metadata to diagnose slow or failing queries;
- cache usage should track hits and misses;
- services should expose performance metrics such as time, memory, and CPU;
- alerts should be configurable for anomalies that matter in production;
- deploys should be monitored and should support rollback when the pipeline or runtime signals a bad release.

## Logging privacy

- do not let logs leak object payloads, secrets, tokens, dumps, or internal fields by accident;
- when tracing needs a human-readable reference, keep it minimal and prefer only `user_id` or the user's name if that is strictly necessary;
- never treat full domain objects as log content;
- keep log output structured and small enough to help debugging without exposing data;
- if a field is not needed to diagnose the issue, leave it out of the log.
