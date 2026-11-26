# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.x (latest) | ✅ |
| < 0.4.0 | ❌ |

Only the latest minor release receives security fixes. We recommend always using the latest version.

## Reporting a Vulnerability

**Please do not report security vulnerabilities via public GitHub Issues.**

To report a vulnerability, email the maintainers at:

**info@vstorm.co**

Include in your report:
- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Any suggested fix (optional)

## Response Timeline

| Stage | Target |
|-------|--------|
| Acknowledgement | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix or mitigation | Within 30 days for critical/high |
| Public disclosure | After fix is released |

We follow coordinated disclosure — we ask that you give us time to release a fix before public disclosure.

## Scope

In scope:
- Remote code execution
- Prompt injection via tool inputs or agent context
- Unsafe deserialization
- Privilege escalation in multi-agent coordination
- Docker sandbox escape
- Sensitive data leakage (MEMORY.md, context files, API keys)

Out of scope:
- Vulnerabilities in third-party dependencies (report to the respective project)
- Issues requiring physical access to the machine
- Social engineering

## Security Features

pydantic-deep includes several security-relevant features:

- **pydantic-ai-shields integration** — 10 guardrails: prompt injection defense, PII detection, secret redaction, cost controls, tool-level access control
- **Docker sandbox** — Sandboxed execution backend for untrusted workloads
- **Budget enforcement** — Hard cost limits prevent runaway agent spend
- **Type-safe inputs** — All tool inputs validated via Pydantic models
- **100% test coverage + Pyright/MyPy strict mode** — Reduces surface for type-related vulnerabilities

## Acknowledgements

We thank all security researchers who responsibly disclose vulnerabilities to us. Confirmed reporters will be credited in the release notes unless they prefer to remain anonymous.
