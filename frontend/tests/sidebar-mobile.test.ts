import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SidebarHarness from './stubs/SidebarHarness.svelte';
import { setTestPathname } from './stubs/state.svelte';
import { fmtRatio, fmtScore, pctNum } from '$lib/utils';
import ScoreRing from '$lib/components/ScoreRing.svelte';
import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
import DataView from '$lib/components/DataView.svelte';
import { confirmDialog } from '$lib/stores/confirm.svelte';

function mockViewport(isMobile: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: isMobile && query.includes('max-width'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  });
}

describe('mobile sidebar, UI primitives, and score formatting', () => {
  beforeEach(() => {
    setTestPathname('/dashboard');
    document.body.innerHTML = '';
  });

  it('opens mobile sidebar when trigger is clicked and stays open until route changes', () => {
    mockViewport(true);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarHarness, { target });
    flushSync();

    // Initially closed on mobile
    expect(document.querySelector('[data-mobile="true"]')).toBeNull();
    // Rail should not render on mobile
    expect(document.querySelector('[data-slot="sidebar-rail"]')).toBeNull();

    // Click trigger to open mobile sidebar
    const trigger = document.querySelector('[data-testid="sidebar-trigger"]') as HTMLButtonElement;
    expect(trigger).not.toBeNull();
    trigger.click();
    flushSync();

    // Mobile sheet content should now be mounted and stay open
    const mobileSidebar = document.querySelector('[data-mobile="true"]');
    expect(mobileSidebar).not.toBeNull();
    expect(mobileSidebar?.getAttribute('data-state')).toBe('open');

    // Route change should automatically close the mobile sidebar
    setTestPathname('/jobs');
    flushSync();
    expect(document.querySelector('[data-mobile="true"]')?.getAttribute('data-state') ?? 'closed').toBe('closed');

    unmount(app);
  });

  it('closes mobile sidebar when clicking a link inside the drawer (even for current route)', () => {
    mockViewport(true);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarHarness, { target });
    flushSync();

    const trigger = document.querySelector('[data-testid="sidebar-trigger"]') as HTMLButtonElement;
    trigger.click();
    flushSync();
    expect(document.querySelector('[data-mobile="true"]')?.getAttribute('data-state')).toBe('open');

    const navLink = document.querySelector('[data-testid="nav-dashboard"]') as HTMLAnchorElement;
    expect(navLink).not.toBeNull();
    navLink.addEventListener('click', (e) => e.preventDefault());
    navLink.click();
    flushSync();

    expect(document.querySelector('[data-mobile="true"]')?.getAttribute('data-state') ?? 'closed').toBe('closed');
    unmount(app);
  });

  it('closes mobile sidebar when clicking the sheet close button', () => {
    mockViewport(true);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarHarness, { target });
    flushSync();

    const trigger = document.querySelector('[data-testid="sidebar-trigger"]') as HTMLButtonElement;
    trigger.click();
    flushSync();
    expect(document.querySelector('[data-mobile="true"]')?.getAttribute('data-state')).toBe('open');

    const closeBtn = document.querySelector('[data-slot="sheet-close"]') as HTMLButtonElement;
    expect(closeBtn).not.toBeNull();
    closeBtn.click();
    flushSync();

    expect(document.querySelector('[data-mobile="true"]')?.getAttribute('data-state') ?? 'closed').toBe('closed');
    unmount(app);
  });

  it('toggles desktop sidebar state between expanded and collapsed on desktop viewport and via shortcut', () => {
    mockViewport(false);
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(SidebarHarness, { target });
    flushSync();

    const desktopSidebar = document.querySelector('[data-slot="sidebar"]');
    expect(desktopSidebar?.getAttribute('data-state')).toBe('expanded');
    expect(document.querySelector('[data-slot="sidebar-rail"]')).not.toBeNull();

    const trigger = document.querySelector('[data-testid="sidebar-trigger"]') as HTMLButtonElement;
    trigger.click();
    flushSync();
    expect(desktopSidebar?.getAttribute('data-state')).toBe('collapsed');

    // Keyboard shortcut Ctrl+B toggles back to expanded
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true }));
    flushSync();
    expect(desktopSidebar?.getAttribute('data-state')).toBe('expanded');

    unmount(app);
  });

  it('formats both 0..1 ratio scores and 0..100 percentage scores accurately in utils and ScoreRing', () => {
    expect(pctNum(null)).toBeNull();
    expect(fmtScore(null)).toBe('Pending');
    expect(fmtScore(0)).toBe('0.0%');
    expect(fmtScore('0.8500')).toBe('85.0%');
    expect(fmtScore(0.924)).toBe('92.4%');
    expect(fmtScore(1)).toBe('100.0%');
    expect(fmtScore(92.4)).toBe('92.4%');
    expect(fmtScore(100)).toBe('100.0%');
    expect(fmtRatio(0.4)).toBe('40.0%');
    expect(fmtRatio(null)).toBe('—');

    const target = document.createElement('div');
    document.body.appendChild(target);
    const ring = mount(ScoreRing, { target, props: { value: 85.4, label: 'Match Score' } });
    flushSync();
    expect(target.querySelector('svg')?.getAttribute('aria-label')).toBe('Match Score: 85.4%');
    expect(target.textContent).toContain('85%');
    unmount(ring);
  });

  it('renders ConfirmDialog with mobile-safe width classes and resolves confirmation', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const dlg = mount(ConfirmDialog, { target });
    flushSync();

    const p = confirmDialog({
      title: 'Reject this application?',
      message: 'Manual decision.',
      confirmLabel: 'Confirm rejection',
      danger: true
    });
    flushSync();

    const content = document.querySelector('[data-slot="alert-dialog-content"]');
    expect(content).not.toBeNull();
    expect(content?.className).toContain('max-w-[calc(100%-2rem)]');
    expect(content?.textContent).toContain('Reject this application?');

    const buttons = Array.from(content?.querySelectorAll('button') ?? []);
    const confirmBtn = buttons.find((b) => b.textContent?.includes('Confirm rejection'));
    expect(confirmBtn).not.toBeUndefined();
    confirmBtn?.click();
    flushSync();

    expect(await p).toBe(true);
    unmount(dlg);
  });

  it('renders extracted resume details in DataView with full-width sections, unwrapped Sourced claims, and aligned tables', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const resumePayload = {
      id: '11111111-2222-3333-4444-555555555555',
      original_filename: 'arjun_mehta_cv.pdf',
      size_bytes: 153600,
      status: 'completed',
      failure_code: null,
      failure_message: null,
      profile: {
        overall_confidence: 0.94,
        extraction_method: 'pdf_text',
        data: {
          full_name: { value: 'Arjun Mehta', confidence: 0.98, evidence: 'Arjun Mehta' },
          contact: {
            email: { value: 'arjun@example.com', confidence: 0.99, evidence: 'arjun@example.com' },
            linkedin_url: { value: null, confidence: null, evidence: null }
          },
          skills: [
            { name: 'Python', category: null, confidence: 0.95, evidence: 'Python' }
          ],
          employment: [
            {
              company: 'BluePeak Analytics',
              title: 'ML Engineer',
              location: null,
              highlights: ['Built ML pipelines', 'Reduced latency by 30%']
            }
          ]
        }
      }
    };

    const view = mount(DataView, { target, props: { value: resumePayload } });
    flushSync();

    const text = target.textContent ?? '';
    expect(text).toContain('arjun_mehta_cv.pdf');
    expect(text).toContain('150 KB');
    expect(text).toContain('94%');
    expect(text).toContain('Arjun Mehta');
    expect(text).toContain('arjun@example.com');
    expect(text).not.toContain('Failure code');
    expect(text).not.toContain('Linkedin url');

    // Employment (even with array field `highlights`) and Skills render as proper aligned tables
    const tables = target.querySelectorAll('table');
    expect(tables.length).toBe(2);
    expect(text).toContain('BluePeak Analytics');
    expect(text).toContain('Built ML pipelines');

    unmount(view);
  });
});
