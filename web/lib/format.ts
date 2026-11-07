/* Money and counts, formatted the same way on every screen. */

export const money = (n: unknown): string => `$${(Number(n) || 0).toFixed(2)}`;

export const num = (n: unknown): string => (Number(n) || 0).toLocaleString("en-GB");
