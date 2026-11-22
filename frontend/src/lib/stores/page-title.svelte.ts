// Reactive store for mapping page/entity IDs to human-readable names (e.g. Job titles, Candidate names)
let titles = $state<Record<string, string>>({});

export const pageTitleStore = {
  setTitle(id: string, title: string) {
    if (!id || !title) return;
    titles[id] = title;
  },
  getTitle(id: string): string | undefined {
    return titles[id];
  },
  getAll(): Record<string, string> {
    return titles;
  },
  clear() {
    titles = {};
  }
};
