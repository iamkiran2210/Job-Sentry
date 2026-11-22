/**
 * Shared semantic and categorical visualization color palette for KPIs and charts.
 * Designed for crisp visual hierarchy and accessibility in both light and dark modes.
 */

export const CATEGORICAL_PALETTE = [
  '#4F46E5', // Indigo 600
  '#0EA5E9', // Sky 500
  '#10B981', // Emerald 500
  '#F59E0B', // Amber 500
  '#EC4899', // Pink 500
  '#8B5CF6', // Violet 500
  '#14B8A6', // Teal 500
  '#F97316' // Orange 500
] as const;

export const LINE_STROKE = '#4F46E5';
export const LINE_ACCENT = '#06B6D4';

/**
 * Returns a semantically meaningful color for recruitment statuses, eligibility,
 * verification outcomes, decisions, and score/completeness buckets; falls back
 * to the high-contrast categorical palette for arbitrary labels (skills, jobs, etc.).
 */
export function colorForLabel(label: string, index = 0): string {
  const norm = label.trim().toLowerCase().replace(/[_-]+/g, ' ');

  // Score buckets (e.g. "0-10", "70-80", "90-100") and completeness buckets ("0-0.25", "0.75-1.0")
  if (norm === 'unscored' || norm === 'n/a' || norm === 'unknown') return '#94A3B8';

  const rangeMatch = label.trim().match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);
  if (rangeMatch) {
    const hi = Number(rangeMatch[2]);
    if (hi <= 1.01) {
      // Data completeness 0..1
      if (hi <= 0.25) return '#F43F5E';
      if (hi <= 0.5) return '#F59E0B';
      if (hi <= 0.75) return '#0EA5E9';
      return '#10B981';
    }
    // Score 0..100
    if (hi <= 20) return '#E11D48';
    if (hi <= 40) return '#F43F5E';
    if (hi <= 50) return '#F97316';
    if (hi <= 60) return '#F59E0B';
    if (hi <= 70) return '#0EA5E9';
    if (hi <= 80) return '#3B82F6';
    if (hi <= 90) return '#14B8A6';
    return '#10B981';
  }

  // Exact or phrase-based semantic matches
  if (/(strong advance|top match|excellent)/i.test(norm)) return '#059669';
  if (/(shortlisted|eligible|passed|succeeded|accept|advance|meets|active|open)/i.test(norm) && !/ineligible|do not|may not/i.test(norm)) {
    return '#10B981';
  }
  if (/(potentially ineligible|do not advance|may not meet|rejected|failed|reject|error|risk)/i.test(norm)) {
    return '#F43F5E';
  }
  if (/(needs review|manual review|hold|processing|in progress|paused|partial|warning|pending)/i.test(norm)) {
    return '#F59E0B';
  }
  if (/(analyzed|completed|ranked|reviewed)/i.test(norm)) return '#6366F1';
  if (/(applied|submitted|uploaded|queued|new)/i.test(norm)) return '#0EA5E9';
  if (/(withdrawn|not verified|archived|closed|draft|skipped|none)/i.test(norm)) return '#94A3B8';

  return CATEGORICAL_PALETTE[Math.abs(index) % CATEGORICAL_PALETTE.length];
}

/** Returns a semantic color for a numeric score ratio (0..1). */
export function colorForRatio(ratio: number): string {
  if (ratio >= 0.75) return '#10B981';
  if (ratio >= 0.55) return '#0EA5E9';
  if (ratio >= 0.35) return '#F59E0B';
  return '#F43F5E';
}

export interface KpiAccent {
  hex: string;
  dot: string;
}

/** Accent color for KPI summary cards based on metric semantics. */
export function kpiAccent(label: string, index = 0): KpiAccent {
  const norm = label.trim().toLowerCase();
  let hex: string;
  if (/shortlist|eligible|pass|succeed|accept/i.test(norm)) {
    hex = '#10B981'; // Emerald
  } else if (/reject|fail|ineligib|risk/i.test(norm)) {
    hex = '#F43F5E'; // Rose
  } else if (/review|process|pending|progress/i.test(norm)) {
    hex = '#F59E0B'; // Amber
  } else if (/score|median|average/i.test(norm)) {
    hex = '#14B8A6'; // Teal
  } else if (/analyz/i.test(norm)) {
    hex = '#8B5CF6'; // Violet
  } else if (/open job|job/i.test(norm)) {
    hex = '#0EA5E9'; // Sky
  } else if (/withdraw|unscored|not verified/i.test(norm)) {
    hex = '#64748B'; // Slate
  } else if (/total|application/i.test(norm)) {
    hex = '#4F46E5'; // Indigo
  } else {
    hex = CATEGORICAL_PALETTE[Math.abs(index) % CATEGORICAL_PALETTE.length];
  }
  return { hex, dot: hex };
}
