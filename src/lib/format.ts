export const STATUS_LABEL: Record<string, string> = {
  'in-progress': '进行中',
  done: '已完成',
  archived: '已归档',
};

export const HOST_LABEL: Record<string, string> = {
  github: 'GitHub',
  gitee: 'Gitee',
  local: 'Local',
};

export function relativeTime(iso: string | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const seconds = (Date.now() - d.getTime()) / 1000;
  if (seconds < 0) return '';
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  if (seconds < 86400 * 30) return `${Math.floor(seconds / 86400)} 天前`;
  if (seconds < 86400 * 365) return `${Math.floor(seconds / (86400 * 30))} 个月前`;
  return `${Math.floor(seconds / (86400 * 365))} 年前`;
}

export function activityClass(iso: string | undefined): string {
  if (!iso) return 'activity-cold';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return 'activity-cold';
  const days = (Date.now() - d.getTime()) / (1000 * 86400);
  if (days < 7) return 'activity-fresh';
  if (days < 30) return 'activity-warm';
  return 'activity-cold';
}

export function groupByCategory<T extends { data: { category: string } }>(items: T[]): Map<string, T[]> {
  const map = new Map<string, T[]>();
  for (const item of items) {
    const cat = item.data.category || 'Other';
    if (!map.has(cat)) map.set(cat, []);
    map.get(cat)!.push(item);
  }
  return new Map([...map.entries()].sort(([a], [b]) => a.localeCompare(b)));
}
