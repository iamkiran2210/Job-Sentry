/** Transition duration that collapses to 0 when the user prefers reduced motion. */
export const dur = (ms: number) => (typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : ms);
