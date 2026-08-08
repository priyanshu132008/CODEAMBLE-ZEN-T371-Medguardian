import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * `cn` — merge conditional class names and de-duplicate conflicting Tailwind
 * utilities (last-one-wins). Used by the shadcn-style primitives in
 * `Components/ui/` and across the MedGuardian UI for composable styling.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}