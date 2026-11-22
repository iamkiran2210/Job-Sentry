<script lang="ts" module>
  type GIS = {
    accounts: {
      id: {
        initialize: (o: Record<string, unknown>) => void;
        renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
        cancel?: () => void;
      };
    };
  };

  let gisLoadPromise: Promise<GIS> | null = null;

  function getGis(): GIS | null {
    const g = (window as unknown as { google?: GIS }).google;
    return g?.accounts?.id ? g : null;
  }

  function loadGisScript(): Promise<GIS> {
    const existing = getGis();
    if (existing) return Promise.resolve(existing);
    if (gisLoadPromise) return gisLoadPromise;

    gisLoadPromise = new Promise<GIS>((resolve, reject) => {
      const finish = () => {
        const g = getGis();
        if (g) resolve(g);
        else {
          gisLoadPromise = null;
          reject(new Error('Google Sign-In loaded, but its API was unavailable.'));
        }
      };

      const prev = document.querySelector<HTMLScriptElement>(
        'script[src^="https://accounts.google.com/gsi/client"]'
      );
      if (prev) {
        if (getGis()) return finish();
        prev.addEventListener('load', finish, { once: true });
        prev.addEventListener(
          'error',
          () => {
            gisLoadPromise = null;
            reject(new Error('Could not load Google Sign-In. Check network or content blockers.'));
          },
          { once: true }
        );
        return;
      }

      const s = document.createElement('script');
      s.src = 'https://accounts.google.com/gsi/client';
      s.async = true;
      s.defer = true;
      s.onload = finish;
      s.onerror = () => {
        gisLoadPromise = null;
        reject(new Error('Could not load Google Sign-In. Check network or content blockers.'));
      };
      document.head.appendChild(s);
    });

    return gisLoadPromise;
  }
</script>

<script lang="ts">
  import { GOOGLE_CLIENT_ID } from '$lib/config';

  let {
    onCredential,
    onError,
    text = 'continue_with'
  }: {
    onCredential: (idToken: string) => void;
    onError: (m: string) => void;
    text?: 'signin_with' | 'signup_with' | 'continue_with';
  } = $props();

  let host = $state<HTMLDivElement>();

  $effect(() => {
    const clientId = GOOGLE_CLIENT_ID.trim();
    const el = host;
    if (!clientId || !el) return;

    let cancelled = false;

    loadGisScript()
      .then((g) => {
        if (cancelled) return;
        // Clamp button width to Google GIS supported bounds (240..400px) so it never collapses at width=0
        const measured = el.clientWidth || el.parentElement?.clientWidth || 320;
        const width = Math.min(400, Math.max(240, Math.floor(measured)));

        g.accounts.id.initialize({
          client_id: clientId,
          ux_mode: 'popup',
          auto_select: false,
          cancel_on_tap_outside: true,
          callback: (r: { credential?: string }) => {
            if (r?.credential) onCredential(r.credential);
            else onError('Google sign-in was cancelled.');
          }
        });

        el.innerHTML = '';
        g.accounts.id.renderButton(el, {
          theme: 'outline',
          size: 'large',
          width,
          text,
          shape: 'rectangular',
          logo_alignment: 'left'
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        onError(err instanceof Error ? err.message : 'Could not load Google Sign-In.');
      });

    return () => {
      cancelled = true;
    };
  });
</script>

{#if GOOGLE_CLIENT_ID}
  <div bind:this={host} class="flex min-h-[44px] w-full items-center justify-center"></div>
{/if}
