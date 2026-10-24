"use client";

import { send } from "@/lib/fetcher";
import type { ReviewTask } from "@/lib/types";

/** POST /reviews/next → the task, or null when the queue is empty (204). */
export async function claimNext(): Promise<ReviewTask | null> {
  return send<ReviewTask | null>("POST", "reviews/next");
}
