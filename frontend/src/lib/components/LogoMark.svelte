<script lang="ts">
  let {
    variant = 'white',
    class: className = 'h-10 w-auto'
  }: {
    variant?: 'white' | 'black';
    class?: string;
  } = $props();
</script>

<img
  src={variant === 'black' ? '/logo-black.png' : '/logo-white.png'}
  alt="Job Sentry"
  class={`object-contain select-none ${className}`}
/>
