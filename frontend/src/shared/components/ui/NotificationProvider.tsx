/**
 * NotificationProvider - Global notification system using MUI Snackbar
 */

import { Alert, Snackbar } from "@mui/material";
import { createContext, useState } from "react";

interface Notification {
  message: string;
  severity: "success" | "error" | "warning" | "info";
  duration?: number;
}

interface NotificationContextType {
  showNotification: (notification: Notification) => void;
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
  showWarning: (message: string) => void;
  showInfo: (message: string) => void;
}

export const NotificationContext = createContext<NotificationContextType | undefined>(
  undefined
);

export function NotificationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [notification, setNotification] = useState<Notification | null>(null);

  const showNotification = (notif: Notification) => {
    setNotification(notif);
  };

  const showSuccess = (message: string) => {
    setNotification({ message, severity: "success", duration: 4000 });
  };

  const showError = (message: string) => {
    setNotification({ message, severity: "error", duration: 6000 });
  };

  const showWarning = (message: string) => {
    setNotification({ message, severity: "warning", duration: 5000 });
  };

  const showInfo = (message: string) => {
    setNotification({ message, severity: "info", duration: 4000 });
  };

  const handleClose = () => {
    setNotification(null);
  };

  return (
    <NotificationContext.Provider
      value={{
        showNotification,
        showSuccess,
        showError,
        showWarning,
        showInfo,
      }}
    >
      {children}
      <Snackbar
        open={!!notification}
        autoHideDuration={notification?.duration || 4000}
        onClose={handleClose}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
      >
        {notification ? (
          <Alert
            onClose={handleClose}
            severity={notification.severity}
            variant="filled"
            sx={{ width: "100%" }}
          >
            {notification.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </NotificationContext.Provider>
  );
}
