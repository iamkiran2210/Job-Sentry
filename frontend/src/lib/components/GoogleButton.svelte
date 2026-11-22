<script lang="ts">
  import { GOOGLE_CLIENT_ID } from '$lib/config';
  let { onCredential, onError }: { onCredential: (idToken: string) => void; onError: (m: string) => void } = $props();
  let host = $state<HTMLDivElement>();
  type GIS = { accounts: { id: { initialize: (o: object) => void; renderButton: (el: HTMLElement, o: object) => void } } };
  const gis = () => (window as unknown as { google?: GIS }).google;

  $effect(() => {
    if (!GOOGLE_CLIENT_ID || !host) return;
    const el = host;
    const init = () => {
      const g = gis();
      if (!g) return onError('Google Sign-In failed to load.');
      g.accounts.id.initialize({ client_id: GOOGLE_CLIENT_ID, callback: (r: { credential?: string }) => (r.credential ? onCredential(r.credential) : onError('Google sign-in was cancelled.')) });
      g.accounts.id.renderButton(el, { theme: 'outline', size: 'large', width: el.clientWidth, text: 'continue_with', shape: 'rectangular' });
    };
    if (gis()) return init();
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client'; s.async = true; s.onload = init; s.onerror = () => onError('Could not load Google Sign-In.');
    document.head.appendChild(s);
  });
</script>
{#if GOOGLE_CLIENT_ID}<div bind:this={host} class="flex w-full justify-center"></div>{/if}
