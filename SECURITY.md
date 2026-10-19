# Security policy

FRS handles biometric data and attendance records. Treat vulnerabilities involving unauthorized recognition, authentication bypass, biometric disclosure, attendance tampering, audit alteration or model-artifact substitution as high priority.

## Reporting a vulnerability

Please do not publish exploit details, production credentials, employee information, face images, embeddings or database exports in a public issue. Use GitHub's private security advisory feature for this repository if it is enabled; otherwise contact the repository maintainers privately before disclosure. Include the affected commit, reproduction steps, expected/actual behavior and a minimal sanitized proof of concept.

There is currently no published service-level agreement for security reports. Do not assume that an unacknowledged report has been accepted or that a fix date is guaranteed.

## Deployment expectations

- Never commit `.env`, API keys, encryption keys, raw images, embeddings, database backups or live audit exports.
- Use HTTPS for any non-loopback network traffic and keep admin credentials separate from kiosk device keys.
- Keep the database and administrative routes off untrusted public networks.
- Pin and verify model artifacts; record full checksums, provenance, licenses and permitted use.
- Keep raw face imagery and embedding arrays out of routine logs.
- Review retention, deletion, access and incident response before collecting real biometric data.
