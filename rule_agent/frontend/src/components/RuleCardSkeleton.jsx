/**
 * Placeholder shown in the rule panel while a rule card is being fetched.
 * Mirrors RuleCard's shape (id badge + category chip, explanation block,
 * a few section cards) using shimmering blocks so layout doesn't jump
 * once the real data arrives.
 */
export default function RuleCardSkeleton() {
  return (
    <div className="rule-card rule-card-skeleton" aria-hidden="true">
      <div className="rule-card-stripe" />

      {/* ── Header ────────────────────────────── */}
      <div className="rule-card-header">
        <div className="rule-header-top">
          <span className="skel-pill skel-shimmer" style={{ width: 110 }} />
          <span className="skel-chip skel-shimmer" style={{ width: 88 }} />
        </div>
      </div>

      {/* ── Business Explanation ────────────── */}
      <div className="explanation-block">
        <div className="explanation-header">
          <span className="section-eyebrow accent">Business Explanation</span>
        </div>
        <div className="skel-lines">
          <span className="skel-line skel-shimmer" style={{ width: '95%' }} />
          <span className="skel-line skel-shimmer" style={{ width: '88%' }} />
          <span className="skel-line skel-shimmer" style={{ width: '62%' }} />
        </div>
      </div>

      {/* ── Section placeholders ────────────── */}
      {[0, 1, 2].map(i => (
        <div className="section-card" key={i}>
          <div className="section-card-header">
            <span className="skel-icon skel-shimmer" />
            <span className="skel-chip skel-shimmer" style={{ width: 96 }} />
          </div>
          <div className="skel-body">
            <span className="skel-line skel-shimmer" style={{ width: '82%' }} />
            <span className="skel-line skel-shimmer" style={{ width: '54%' }} />
          </div>
        </div>
      ))}
    </div>
  )
}
