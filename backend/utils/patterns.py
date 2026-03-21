"""
patterns.py
All regex patterns for GhostScan secret detection.

Design principles:
- Specific patterns (OpenAI, Stripe, AWS, etc.) are high-confidence → run always
- Generic patterns (bearer token, hardcoded password) have false-positive risk
  → kept but with minimum length guards enforced in ghostscan.py (_scan_text skips len < 8)
- Patterns marked is_safe_in_frontend=True are INFO severity (publishable keys, Firebase)
- Patterns are ordered: most specific first
"""

SECRET_PATTERNS = [

    # ── OpenAI ────────────────────────────────────────────────────────────────
    {
        "name": "OpenAI API Key",
        "regex": r"sk-[a-zA-Z0-9]{48}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Move to server-side env var. Never expose in client.",
    },
    {
        "name": "OpenAI API Key (new format)",
        "regex": r"sk-proj-[a-zA-Z0-9\-_]{40,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Move to server-side env var.",
    },

    # ── Anthropic ─────────────────────────────────────────────────────────────
    {
        "name": "Anthropic API Key",
        "regex": r"sk-ant-[a-zA-Z0-9\-]{90,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Move to server-side env var.",
    },

    # ── Groq ──────────────────────────────────────────────────────────────────
    {
        "name": "Groq API Key",
        "regex": r"gsk_[a-zA-Z0-9]{52}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Move to server-side env var.",
    },

    # ── Stripe ────────────────────────────────────────────────────────────────
    {
        "name": "Stripe Secret Key",
        "regex": r"sk_live_[a-zA-Z0-9]{24,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate NOW. Stripe secret keys must never appear in frontend code.",
    },
    {
        "name": "Stripe Test Secret Key",
        "regex": r"sk_test_[a-zA-Z0-9]{24,}",
        "severity": "WARNING",
        "is_safe_in_frontend": False,
        "recommendation": "Test secret keys should not be in frontend code either.",
    },
    {
        "name": "Stripe Publishable Key",
        "regex": r"pk_live_[a-zA-Z0-9]{24,}",
        "severity": "INFO",
        "is_safe_in_frontend": True,
        "note": "Publishable keys are designed for frontend use — this is expected.",
        "recommendation": "This is expected. Publishable keys are intentionally public.",
    },
    {
        "name": "Stripe Webhook Secret",
        "regex": r"whsec_[a-zA-Z0-9]{32,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Webhook secrets must only be on the server.",
    },

    # ── AWS ───────────────────────────────────────────────────────────────────
    {
        "name": "AWS Access Key ID",
        "regex": r"AKIA[0-9A-Z]{16}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Use IAM roles. Never embed AWS keys in frontend.",
    },
    {
        "name": "AWS Secret Access Key",
        "regex": r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. AWS secret keys must never be in frontend code.",
    },

    # ── Google ────────────────────────────────────────────────────────────────
    {
        "name": "Google API Key",
        "regex": r"AIza[0-9A-Za-z\-_]{35}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Restrict this key in GCP Console to specific APIs and HTTP referrers.",
    },
    {
        "name": "Google OAuth Client Secret",
        "regex": r"GOCSPX-[a-zA-Z0-9\-_]{28,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. OAuth client secrets must be server-side only.",
    },
    {
        "name": "Google Service Account Key",
        "regex": r'"private_key_id"\s*:\s*"[a-f0-9]{40}"',
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Service account JSON must never be in frontend.",
    },

    # ── GitHub ────────────────────────────────────────────────────────────────
    {
        "name": "GitHub Personal Access Token",
        "regex": r"ghp_[a-zA-Z0-9]{36}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Use server-side GitHub API calls only.",
    },
    {
        "name": "GitHub OAuth Token",
        "regex": r"gho_[a-zA-Z0-9]{36}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Never expose OAuth tokens in frontend.",
    },
    {
        "name": "GitHub Actions Token",
        "regex": r"ghs_[a-zA-Z0-9]{36}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Actions tokens must never appear in frontend.",
    },
    {
        "name": "GitHub Fine-Grained Token",
        "regex": r"github_pat_[a-zA-Z0-9_]{82}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately.",
    },

    # ── Twilio ────────────────────────────────────────────────────────────────
    {
        "name": "Twilio API Key SID",
        "regex": r"SK[a-f0-9]{32}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Move to server-side. Never embed Twilio credentials in frontend.",
    },
    {
        "name": "Twilio Account SID",
        "regex": r"AC[a-f0-9]{32}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Twilio Account SIDs should remain server-side.",
    },

    # ── SendGrid ──────────────────────────────────────────────────────────────
    {
        "name": "SendGrid API Key",
        "regex": r"SG\.[a-zA-Z0-9\-_]{22}\.[a-zA-Z0-9\-_]{43}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Move to server-side. Rotate if already exposed.",
    },

    # ── Slack ─────────────────────────────────────────────────────────────────
    {
        "name": "Slack Bot Token",
        "regex": r"xoxb-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{23,25}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Slack bot tokens must never appear in frontend.",
    },
    {
        "name": "Slack User Token",
        "regex": r"xoxp-[0-9]{10,13}-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{32}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Slack user tokens grant full account access.",
    },
    {
        "name": "Slack Webhook URL",
        "regex": r"https://hooks\.slack\.com/services/T[a-zA-Z0-9]+/B[a-zA-Z0-9]+/[a-zA-Z0-9]+",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate webhook URL. Anyone with it can post to your Slack.",
    },

    # ── Mailgun ───────────────────────────────────────────────────────────────
    {
        "name": "Mailgun API Key",
        "regex": r"key-[a-zA-Z0-9]{32}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Move to server-side. Rotate if exposed.",
    },

    # ── Razorpay ──────────────────────────────────────────────────────────────
    {
        "name": "Razorpay Secret Key",
        "regex": r"rzp_live_[a-zA-Z0-9]{20,}",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Rotate immediately. Razorpay secret keys must be server-side only.",
    },
    {
        "name": "Razorpay Test Secret Key",
        "regex": r"rzp_test_[a-zA-Z0-9]{20,}",
        "severity": "WARNING",
        "is_safe_in_frontend": False,
        "recommendation": "Test secret keys should not be in frontend code.",
    },

    # ── Firebase ──────────────────────────────────────────────────────────────
    {
        "name": "Firebase API Key",
        "regex": r"AIza[0-9A-Za-z\-_]{35}",
        "severity": "WARNING",
        "is_safe_in_frontend": True,
        "note": "Firebase keys are often intentionally public — but must be restricted in Firebase Console.",
        "recommendation": "Restrict this key in Firebase Console to your domain and specific services.",
    },

    # ── JWT / Auth tokens ─────────────────────────────────────────────────────
    {
        "name": "JWT Secret / Signing Key",
        "regex": r"""(?:jwt.?secret|jwt.?key|signing.?secret)['\"\s:=]+['"]([\w\-\.]{20,})['\"]""",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "JWT signing secrets must never be in frontend code. Move to server env var.",
    },
    {
        "name": "Bearer Token in Request Header",
        "regex": r"[Bb]earer\s+[a-zA-Z0-9\-_\.]{30,}",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Don't send bearer tokens directly from frontend. Use a server-side proxy.",
    },

    # ── Private keys ──────────────────────────────────────────────────────────
    {
        "name": "Private Key (PEM)",
        "regex": r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Remove immediately. Private keys must never be in frontend code.",
    },

    # ── Database credentials ──────────────────────────────────────────────────
    {
        "name": "Database Connection String",
        "regex": r"(?:mongodb|postgres|postgresql|mysql|redis)://[^:]+:[^@\s]{8,}@[^\s\"']+",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Remove immediately. Database connection strings must never be in frontend.",
    },
    {
        "name": "Password in URL",
        "regex": r"https?://[^:@\s]+:[^@\s]{8,}@[^\s\"']+",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Never embed credentials in URLs. Use proper authentication.",
    },

    # ── Framework env leaks ────────────────────────────────────────────────────
    {
        "name": "Exposed Framework Secret Env Var",
        "regex": r"""(?:NEXT_PUBLIC_|VITE_|REACT_APP_)[A-Z_]*(?:SECRET|KEY|TOKEN|PASSWORD|AUTH)[A-Z_]*['\"\s:=]+['"]([a-zA-Z0-9\-_\.]{16,})['"]""",
        "severity": "CRITICAL",
        "is_safe_in_frontend": False,
        "recommendation": "Remove SECRET/KEY/TOKEN vars from NEXT_PUBLIC_/VITE_/REACT_APP_ prefix immediately.",
    },

    # ── Generic high-confidence ────────────────────────────────────────────────
    {
        "name": "Hardcoded API Key in JS",
        "regex": r"""(?:api.?key|apikey|api_key)\s*[=:]\s*['"]([a-zA-Z0-9\-_]{20,})['"]""",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Move hardcoded API keys to server-side environment variables.",
    },
    {
        "name": "Hardcoded Secret in JS",
        "regex": r"""(?:secret|private.?key|auth.?token)\s*[=:]\s*['"]([a-zA-Z0-9\-_\.]{20,})['"]""",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Move hardcoded secrets to server-side environment variables.",
    },
    {
        "name": "Hardcoded Password in JS",
        "regex": r"""(?:password|passwd|pwd)\s*[=:]\s*['"]([a-zA-Z0-9!@#$%^&*\-_]{8,})['"]""",
        "severity": "HIGH",
        "is_safe_in_frontend": False,
        "recommendation": "Remove hardcoded passwords. Use environment variables and proper auth.",
    },
]