import { AppRouter } from "./router/AppRouter";

// Import shared modules to ensure they are type-checked
import "./hooks/useSSE";
import "./shared/api";
import "./shared/auth";
import "./shared/sse";
import "./shared/types";

/**
 * Root application component.
 *
 * Wraps the entire app with routing and layout.
 */

function App() {
  return <AppRouter />;
}

export default App;
