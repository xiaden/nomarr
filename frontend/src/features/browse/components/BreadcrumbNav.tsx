/**
 * BreadcrumbNav - Navigation breadcrumb for hierarchical browsing
 *
 * Shows: Artist → Album → Track + last 3 tag hops
 */

import { ChevronRight } from "@mui/icons-material";
import { Box, Breadcrumbs, Link, Typography } from "@mui/material";

export interface BreadcrumbItem {
  label: string;
  onClick: () => void;
}

interface BreadcrumbNavProps {
  items: BreadcrumbItem[];
}

export function BreadcrumbNav({ items }: BreadcrumbNavProps) {
  if (items.length === 0) {
    return null;
  }

  return (
    <Box sx={{ py: 1 }}>
      <Breadcrumbs
        separator={<ChevronRight fontSize="small" />}
        maxItems={7}
        aria-label="library navigation"
      >
        {items.map((item, index) => {
          const isLast = index === items.length - 1;

          if (isLast) {
            return (
              <Typography key={index} color="text.primary" variant="body2">
                {item.label}
              </Typography>
            );
          }

          return (
            <Link
              key={index}
              component="button"
              variant="body2"
              onClick={item.onClick}
              underline="hover"
              color="inherit"
              sx={{ cursor: "pointer" }}
            >
              {item.label}
            </Link>
          );
        })}
      </Breadcrumbs>
    </Box>
  );
}
