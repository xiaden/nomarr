import { AppRouter } from "./router/AppRouter";
import { NotificationProvider } from "./shared/components/ui";

// Import shared modules to ensure they are type-checked
import "./hooks/useSSE";
import "./shared/api";
import "./shared/auth";
import "./shared/sse";
import "./shared/types";

/**
 * Root application component.
 *
 * Wraps the entire app with routing, layout, and global notification system.
 */

function App() {
  return (
    <NotificationProvider>
      <AppRouter />
    </NotificationProvider>
  );
}

export default App;
