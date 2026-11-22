let pathname = $state('/dashboard');
let searchParams = $state(new URLSearchParams());

export const page = {
  get url() {
    return {
      get pathname() {
        return pathname;
      },
      get searchParams() {
        return searchParams;
      }
    };
  },
  params: {} as Record<string, string>
};

export function setTestPathname(next: string) {
  pathname = next;
}
