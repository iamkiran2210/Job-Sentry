import { describe, expect, it } from 'vitest';
import { CATEGORICAL_PALETTE, colorForLabel, colorForRatio, kpiAccent } from '$lib/viz-colors';

describe('viz-colors', () => {
  it('maps recruitment statuses and outcomes to semantic colors', () => {
    expect(colorForLabel('Shortlisted')).toBe('#10B981');
    expect(colorForLabel('Rejected')).toBe('#F43F5E');
    expect(colorForLabel('Needs review')).toBe('#F59E0B');
    expect(colorForLabel('Analyzed')).toBe('#6366F1');
    expect(colorForLabel('Applied')).toBe('#0EA5E9');
    expect(colorForLabel('Withdrawn')).toBe('#94A3B8');
    expect(colorForLabel('Potentially ineligible')).toBe('#F43F5E');
    expect(colorForLabel('Eligible')).toBe('#10B981');
  });

  it('maps score and completeness buckets to progressive heat colors', () => {
    expect(colorForLabel('10-20')).toBe('#E11D48');
    expect(colorForLabel('50-60')).toBe('#F59E0B');
    expect(colorForLabel('70-80')).toBe('#3B82F6');
    expect(colorForLabel('90-100')).toBe('#10B981');
    expect(colorForLabel('unscored')).toBe('#94A3B8');
    expect(colorForLabel('0-0.25')).toBe('#F43F5E');
    expect(colorForLabel('0.75-1.0')).toBe('#10B981');
  });

  it('falls back to categorical palette for arbitrary skill/job labels', () => {
    expect(colorForLabel('Python', 0)).toBe(CATEGORICAL_PALETTE[0]);
    expect(colorForLabel('Kubernetes', 1)).toBe(CATEGORICAL_PALETTE[1]);
  });

  it('assigns semantic KPI card accents and score ratios', () => {
    expect(kpiAccent('Shortlisted count').hex).toBe('#10B981');
    expect(kpiAccent('Rejected count').hex).toBe('#F43F5E');
    expect(kpiAccent('Average latest score').hex).toBe('#14B8A6');
    expect(kpiAccent('Open jobs').hex).toBe('#0EA5E9');
    expect(colorForRatio(0.85)).toBe('#10B981');
    expect(colorForRatio(0.2)).toBe('#F43F5E');
  });
});
