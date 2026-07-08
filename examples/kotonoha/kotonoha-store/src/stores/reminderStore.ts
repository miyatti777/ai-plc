/**
 * reminderStore — 補充リマインドの管理画面向けクライアント状態（zustand想定）。
 * 責務: 運用担当者が配信候補プレビュー・配信履歴を確認するための一次状態。S2の運用ダッシュボードで使用。
 */

import type { ReminderCandidate } from "../services/ReminderService.js";

export interface ReminderState {
  /** findDueForReminder のプレビュー結果 */
  candidates: ReminderCandidate[];
  loading: boolean;
  setCandidates: (candidates: ReminderCandidate[]) => void;
}

// TODO(S2): create<ReminderState>()((set) => ({ ... })) で zustand ストアを実装する
export const reminderStoreDefinition = (): ReminderState => ({
  candidates: [],
  loading: false,
  setCandidates: () => {
    /* TODO */
  },
});
