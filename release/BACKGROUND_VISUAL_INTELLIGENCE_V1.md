# VANTA 73 — Background Visual Intelligence v1

## User workflow

1. Attach a genuine background artwork PNG/JPG to a Discord message.
2. Run `!background_analyze my moonlit shrine with glowing portal` alongside the attachment.
3. Review the observed scene elements, central-avatar clearance, crop risks, source-export checks, proposed descriptive titles and description, IP caution, and the **single bounded AssetType 92** live category search.
4. In VANTA's private conversation, reply `yes` to optionally send the visual observations into existing `!chain` title generation. This is a separate user-authorized step with its own AI quota.
5. Use actual creator sales / favorites results, and impression/click data if available, to compare launched title variants. No expected revenue or measured CTR is implied.

## Enforcement

- New command is owner-only, AI-cost classified, and uses existing centralized pre-invoke authorization.
- One vision provider pass with existing Gemini/OpenRouter fallback, reused keys and existing rate limits. Maximum 2 attachments, PNG/JPG/BMP MIME only, 8MB each.
- One optional, bounded category-filtered marketplace query via shared scheduler, one page maximum. Failed HTTP/429 is described as unavailable, never zero competitors.
- No automatic image upload, marketplace purchase, listing publication, database mutation, third-party data retention, or unapproved command.
- Export validation checks known 2560×1440 RGB PNG/JPEG metadata; no claim to simulate Roblox crop accurately.
- New title candidates derived from creator notes / model-observed scene, verified against existing forbidden-name guard; they are **not verified high-CTR titles**.
- Competitor image visual comparison, actual click-through/impression telemetry, and complete Roblox catalog scans are **not implemented**.

## Validation gates

- `test_background_visual_intelligence.py` for scene observations, grounded candidate names, explicit failed-live evidence, owner-only AI classification, and command callback with fake image/network providers.
- Existing background tests, all 91 registered command security checks, runtime inventory, sales and Postgres integration CI must pass.
- Staging Discord smoke with an actual user image and owner permissions before production deployment.
- Preserve manual Oracle schema-gated production deployment; do not auto-deploy this PR.

## Interpretation

Use this as a **decision-support tool**. Stronger titles are a hypothesis to test; there is no scientifically validated CTR predictor. Category-wide supply, conversion rate, and actual revenue must never be inferred from a bounded search sample or favorites.
