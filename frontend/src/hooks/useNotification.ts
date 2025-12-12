/**
 * useNotification - Hook for showing notifications via Snackbar
 */

import { useContext } from "react";

import { NotificationContext } from "../shared/components/ui/NotificationProvider";

export function useNotification() {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error(
      "useNotification must be used within NotificationProvider"
    );
  }
  return context;
}

