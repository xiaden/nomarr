import { ThemeProvider } from "@mui/material/styles";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom";

import { theme } from "../theme";

interface ExtendedRenderOptions extends RenderOptions {
  routerProps?: MemoryRouterProps;
}

/**
 * Render with MUI ThemeProvider and optional MemoryRouter.
 *
 * Use instead of bare `render()` when the component needs theme or routing.
 */
export function renderWithProviders(
  ui: ReactElement,
  { routerProps, ...options }: ExtendedRenderOptions = {},
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ThemeProvider theme={theme}>
        <MemoryRouter {...routerProps}>{children}</MemoryRouter>
      </ThemeProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...options });
}

export { screen, within, waitFor } from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";
