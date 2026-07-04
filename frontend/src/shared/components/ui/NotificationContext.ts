/**
 * NotificationContext - Context and types for the global notification system
 */

import { createContext } from "react";

export interface Notification {
  message: string;
  severity: "success" | "error" | "warning" | "info";
  duration?: number;
}

export interface NotificationContextType {
  showNotification: (notification: Notification) => void;
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
  showWarning: (message: string) => void;
  showInfo: (message: string) => void;
}

export const NotificationContext = createContext<
  NotificationContextType | undefined
>(undefined);
