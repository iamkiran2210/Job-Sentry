/**
 * Client-side CSV and native Excel (.xlsx) export for the Applicant Ranking table.
 * Pure TypeScript with zero external dependencies.
 */

import {
  DECISION_OUTCOME_LABEL,
  ELIGIBILITY_LABEL,
  type RankedItem
} from '$lib/types/application';
import { fmtDateTime, fmtRatio, fmtScore, humanize, shortId } from '$lib/utils';

export interface RankingExportRow {
  rank: number;
  applicant_name: string;
  email: string;
  overall_score: string;
  skills_score: string;
  decision_agent: string;
  ai_decision: string;
  ai_confidence: string;
  ai_summary: string;
  mandatory_requirements: string;
  data_completeness: string;
  verification_status: string;
  application_status: string;
  applied_at: string;
  application_id: string;
}

export const EXPORT_COLUMNS: { key: keyof RankingExportRow; header: string; width: number }[] = [
  { key: 'rank', header: 'Rank', width: 8 },
  { key: 'applicant_name', header: 'Applicant Name', width: 24 },
  { key: 'email', header: 'Email', width: 28 },
  { key: 'overall_score', header: 'Overall Score', width: 15 },
  { key: 'skills_score', header: 'Skills Score', width: 14 },
  { key: 'decision_agent', header: 'Decision Agent', width: 24 },
  { key: 'ai_decision', header: 'AI Decision', width: 18 },
  { key: 'ai_confidence', header: 'AI Confidence', width: 15 },
  { key: 'ai_summary', header: 'AI Decision Summary', width: 46 },
  { key: 'mandatory_requirements', header: 'Mandatory Requirements', width: 28 },
  { key: 'data_completeness', header: 'Completeness', width: 14 },
  { key: 'verification_status', header: 'Verification', width: 18 },
  { key: 'application_status', header: 'Application Status', width: 18 },
  { key: 'applied_at', header: 'Applied At', width: 20 },
  { key: 'application_id', header: 'Application ID', width: 38 }
];

export function buildExportRows(
  items: RankedItem[],
  opts: {
    names?: Record<string, string>;
    emails?: Record<string, string>;
    agentName?: string;
  } = {}
): RankingExportRow[] {
  const { names = {}, emails = {}, agentName = 'Balanced Hiring Manager' } = opts;
  return items.map((it) => {
    const name =
      names[it.application_id] ||
      it.candidate_name ||
      `Application ${shortId(it.application_id)}`;
    const decision = it.decision;
    const verification = Array.isArray(it.verification_statuses) && it.verification_statuses.length
      ? it.verification_statuses.map((s) => humanize(s)).join(', ')
      : 'Not verified';
    return {
      rank: it.rank,
      applicant_name: name,
      email: emails[it.application_id] || '',
      overall_score: fmtScore(it.score),
      skills_score: fmtScore(it.skills_score),
      decision_agent: decision?.agent_name || agentName,
      ai_decision: decision
        ? DECISION_OUTCOME_LABEL[decision.decision] ?? humanize(decision.decision)
        : 'Pending',
      ai_confidence: decision ? `${Math.round((decision.confidence ?? 0) * 100)}%` : '—',
      ai_summary: decision?.summary ?? '',
      mandatory_requirements: it.eligibility
        ? ELIGIBILITY_LABEL[it.eligibility] ?? humanize(it.eligibility)
        : 'Pending',
      data_completeness: fmtRatio(it.data_completeness),
      verification_status: verification,
      application_status: it.status ? humanize(it.status) : '—',
      applied_at: it.application_created_at ? fmtDateTime(it.application_created_at) : '',
      application_id: it.application_id
    };
  });
}

function sanitizeSpreadsheetCell(value: string): string {
  // Neutralize CSV/Excel formula injection while preserving numbers and clean text
  if (/^[=+\-@\t\r]/.test(value)) return `'${value}`;
  return value;
}

function csvCell(raw: string | number): string {
  const str = typeof raw === 'number' ? String(raw) : sanitizeSpreadsheetCell(String(raw ?? ''));
  if (/[",\r\n]/.test(str)) return `"${str.replace(/"/g, '""')}"`;
  return str;
}

/** Generate RFC-4180 UTF-8 CSV (with BOM for seamless Microsoft Excel opening). */
export function toCsv(rows: RankingExportRow[]): string {
  const headerLine = EXPORT_COLUMNS.map((c) => csvCell(c.header)).join(',');
  const dataLines = rows.map((row) =>
    EXPORT_COLUMNS.map((c) => csvCell(row[c.key])).join(',')
  );
  return '\uFEFF' + [headerLine, ...dataLines].join('\r\n') + '\r\n';
}

// ---------------------------------------------------------------------------
// Minimal native Office Open XML (.xlsx) builder (ZIP Store method + CRC-32)
// ---------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function xmlEsc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
    // Strip illegal XML 1.0 control characters
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
}

function colLetter(idx: number): string {
  let n = idx + 1;
  let out = '';
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function buildWorksheetXml(rows: RankingExportRow[]): string {
  const colsXml = EXPORT_COLUMNS.map(
    (c, idx) => `<col min="${idx + 1}" max="${idx + 1}" width="${c.width}" customWidth="1"/>`
  ).join('');

  const headerCells = EXPORT_COLUMNS.map(
    (c, idx) =>
      `<c r="${colLetter(idx)}1" t="inlineStr" s="1"><is><t>${xmlEsc(c.header)}</t></is></c>`
  ).join('');

  const bodyRows = rows
    .map((row, rIdx) => {
      const excelRow = rIdx + 2;
      const cells = EXPORT_COLUMNS.map((c, cIdx) => {
        const ref = `${colLetter(cIdx)}${excelRow}`;
        const val = row[c.key];
        if (typeof val === 'number' && Number.isFinite(val)) {
          return `<c r="${ref}"><v>${val}</v></c>`;
        }
        const safe = sanitizeSpreadsheetCell(String(val ?? ''));
        return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlEsc(safe)}</t></is></c>`;
      }).join('');
      return `<row r="${excelRow}">${cells}</row>`;
    })
    .join('');

  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' +
    `<cols>${colsXml}</cols>` +
    `<sheetData><row r="1">${headerCells}</row>${bodyRows}</sheetData>` +
    '</worksheet>'
  );
}

function zipStore(entries: { name: string; data: Uint8Array }[]): Uint8Array {
  const enc = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;

  for (const e of entries) {
    const nameBytes = enc.encode(e.name);
    const crc = crc32(e.data);
    const size = e.data.length;

    const local = new Uint8Array(30 + nameBytes.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0, true);
    lv.setUint16(8, 0, true); // store (no compression)
    lv.setUint16(10, 0, true);
    lv.setUint16(12, 0, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, size, true);
    lv.setUint32(22, size, true);
    lv.setUint16(26, nameBytes.length, true);
    lv.setUint16(28, 0, true);
    local.set(nameBytes, 30);

    const central = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0, true);
    cv.setUint16(10, 0, true);
    cv.setUint16(12, 0, true);
    cv.setUint16(14, 0, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, size, true);
    cv.setUint32(24, size, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint16(30, 0, true);
    cv.setUint16(32, 0, true);
    cv.setUint16(34, 0, true);
    cv.setUint16(36, 0, true);
    cv.setUint32(38, 0, true);
    cv.setUint32(42, offset, true);
    central.set(nameBytes, 46);

    localParts.push(local, e.data);
    centralParts.push(central);
    offset += local.length + e.data.length;
  }

  const centralSize = centralParts.reduce((a, b) => a + b.length, 0);
  const eocd = new Uint8Array(22);
  const ev = new DataView(eocd.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(4, 0, true);
  ev.setUint16(6, 0, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, centralSize, true);
  ev.setUint32(16, offset, true);
  ev.setUint16(20, 0, true);

  const totalLen = offset + centralSize + eocd.length;
  const out = new Uint8Array(totalLen);
  let cursor = 0;
  for (const p of localParts) {
    out.set(p, cursor);
    cursor += p.length;
  }
  for (const p of centralParts) {
    out.set(p, cursor);
    cursor += p.length;
  }
  out.set(eocd, cursor);
  return out;
}

/** Generate a valid Office Open XML (.xlsx) workbook buffer. */
export function toXlsx(rows: RankingExportRow[], sheetName = 'Applicant Ranking'): Uint8Array {
  const enc = new TextEncoder();
  const safeSheet = xmlEsc(sheetName.replace(/[\\/?*[\]:]/g, '').slice(0, 31) || 'Ranking');

  const contentTypes =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
    '</Types>';

  const rootRels =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
    '</Relationships>';

  const workbook =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
    `<sheets><sheet name="${safeSheet}" sheetId="1" r:id="rId1"/></sheets>` +
    '</workbook>';

  const workbookRels =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
    '</Relationships>';

  const styles =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    '<fonts count="2">' +
    '<font><sz val="11"/><name val="Calibri"/></font>' +
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>' +
    '</fonts>' +
    '<fills count="3">' +
    '<fill><patternFill patternType="none"/></fill>' +
    '<fill><patternFill patternType="gray125"/></fill>' +
    '<fill><patternFill patternType="solid"><fgColor rgb="FF4F46E5"/></patternFill></fill>' +
    '</fills>' +
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>' +
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
    '<cellXfs count="2">' +
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>' +
    '</cellXfs>' +
    '</styleSheet>';

  const sheetXml = buildWorksheetXml(rows);

  return zipStore([
    { name: '[Content_Types].xml', data: enc.encode(contentTypes) },
    { name: '_rels/.rels', data: enc.encode(rootRels) },
    { name: 'xl/workbook.xml', data: enc.encode(workbook) },
    { name: 'xl/_rels/workbook.xml.rels', data: enc.encode(workbookRels) },
    { name: 'xl/styles.xml', data: enc.encode(styles) },
    { name: 'xl/worksheets/sheet1.xml', data: enc.encode(sheetXml) }
  ]);
}

export function triggerFileDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    a.remove();
    URL.revokeObjectURL(url);
  }, 150);
}

export function makeExportFilename(jobSlug: string, ext: 'csv' | 'xlsx'): string {
  const clean = jobSlug
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  const stamp = new Date().toISOString().slice(0, 10);
  return `${clean || 'applicants'}-ranking-${stamp}.${ext}`;
}
