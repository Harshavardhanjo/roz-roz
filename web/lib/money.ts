// Mirrors the backend's app/money.py so the frontend's display matches the API's own formatting.

export function rupees(paise: number): number {
  return paise % 100 === 0 ? paise / 100 : Math.round((paise / 100) * 100) / 100;
}

// paise -> "₹12,345.67" (Indian digit grouping); 150000 -> "₹1,500"
export function inr(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const whole = Math.floor(abs / 100);
  const fraction = abs % 100;

  let digits = String(whole);
  if (digits.length > 3) {
    const tail = digits.slice(-3);
    let head = digits.slice(0, -3);
    const groups: string[] = [];
    while (head.length > 2) {
      groups.unshift(head.slice(-2));
      head = head.slice(0, -2);
    }
    if (head) groups.unshift(head);
    digits = [...groups, tail].join(",");
  }

  return `${sign}₹${digits}${fraction ? `.${String(fraction).padStart(2, "0")}` : ""}`;
}

export function paiseFromRupeeInput(value: string): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round(n * 100);
}
