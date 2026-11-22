import { describe, expect, it } from 'vitest';
import {
  buildExportRows,
  makeExportFilename,
  toCsv,
  toXlsx
} from '$lib/export-ranking';
import type { RankedItem } from '$lib/types/application';

const sampleItems: RankedItem[] = [
  {
    rank: 1,
    application_id: 'app-11111111-2222-3333-4444-555555555555',
    candidate_name: 'Alice, Jr.',
    score: 88.4,
    skills_score: 92,
    eligibility: 'eligible',
    data_completeness: 0.95,
    status: 'shortlisted',
    verification_statuses: ['passed'],
    decision: {
      agent_id: 'balanced',
      agent_name: 'Balanced Hiring Manager',
      decision: 'strong_advance',
      confidence: 0.91,
      summary: 'Strong Python & FastAPI background.',
      next_step: 'Schedule technical interview',
      key_factors: ['Python'],
      risk_flags: []
    }
  },
  {
    rank: 2,
    application_id: 'app-22222222-3333-4444-5555-666666666666',
    candidate_name: '=CMD()',
    score: 42,
    skills_score: 50,
    eligibility: 'needs_review',
    data_completeness: 0.6,
    status: 'analyzed',
    verification_statuses: ['needs_review'],
    decision: null
  }
];

describe('export-ranking', () => {
  it('builds structured rows and escapes CSV commas and formula prefixes', () => {
    const rows = buildExportRows(sampleItems, {
      emails: { 'app-11111111-2222-3333-4444-555555555555': 'alice@example.com' }
    });
    expect(rows).toHaveLength(2);
    expect(rows[0].email).toBe('alice@example.com');
    expect(rows[0].ai_decision).toBe('Strong Advance');
    expect(rows[1].ai_decision).toBe('Pending');

    const csv = toCsv(rows);
    expect(csv.startsWith('\uFEFFRank,Applicant Name,Email,')).toBe(true);
    expect(csv).toContain('"Alice, Jr."');
    expect(csv).toContain("'=CMD()");
  });

  it('produces a valid ZIP-backed Office Open XML (.xlsx) workbook', () => {
    const rows = buildExportRows(sampleItems);
    const bytes = toXlsx(rows, 'Backend Engineer');
    // ZIP local file header magic PK\x03\x04
    expect(bytes[0]).toBe(0x50);
    expect(bytes[1]).toBe(0x4b);
    expect(bytes[2]).toBe(0x03);
    expect(bytes[3]).toBe(0x04);
    const text = new TextDecoder().decode(bytes);
    expect(text).toContain('[Content_Types].xml');
    expect(text).toContain('xl/worksheets/sheet1.xml');
    expect(text).toContain('Alice, Jr.');
    expect(text).toContain('&apos;=CMD()');
  });

  it('generates clean export filenames', () => {
    const fn = makeExportFilename('Senior Backend Engineer (ML)', 'xlsx');
    expect(fn).toMatch(/^senior-backend-engineer-ml-ranking-\d{4}-\d{2}-\d{2}\.xlsx$/);
  });
});
