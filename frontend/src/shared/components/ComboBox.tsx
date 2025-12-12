/**
 * ComboBox component - combines text input with dropdown selection
 * Uses MUI theme for consistent styling
 */

import type { BoxProps } from "@mui/material";
import { Box, TextField } from "@mui/material";
import { useEffect, useRef, useState } from "react";

interface ComboBoxProps extends Omit<BoxProps, "onChange"> {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  disabled?: boolean;
}

export function ComboBox({
  value,
  onChange,
  options,
  placeholder = "Type or select...",
  disabled = false,
  ...props
}: ComboBoxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [filteredOptions, setFilteredOptions] = useState<string[]>(options);
  const containerRef = useRef<HTMLDivElement>(null);

  // Filter options based on input value
  useEffect(() => {
    if (value) {
      const filtered = options.filter((option) =>
        option.toLowerCase().includes(value.toLowerCase())
      );
      setFilteredOptions(filtered);
    } else {
      setFilteredOptions(options);
    }
  }, [value, options]);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
    setIsOpen(true);
  };

  const handleOptionClick = (option: string) => {
    onChange(option);
    setIsOpen(false);
  };

  return (
    <Box
      {...props}
      ref={containerRef}
      sx={{
        position: "relative",
        ...props.sx,
      }}
    >
      <TextField
        type="text"
        value={value}
        onChange={handleInputChange}
        onFocus={() => setIsOpen(true)}
        placeholder={placeholder}
        disabled={disabled}
        fullWidth
        size="small"
        sx={{
          "& .MuiOutlinedInput-root": {
            bgcolor: disabled ? "background.paper" : "background.default",
          },
        }}
      />

      {isOpen && !disabled && filteredOptions.length > 0 && (
        <Box
          sx={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            maxHeight: "200px",
            overflowY: "auto",
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            borderTop: "none",
            borderRadius: "0 0 4px 4px",
            boxShadow: 2,
            zIndex: 1000,
          }}
        >
          {filteredOptions.map((option, index) => (
            <Box
              key={index}
              onClick={() => handleOptionClick(option)}
              sx={{
                p: 1.5,
                cursor: "pointer",
                fontSize: "0.875rem",
                borderBottom:
                  index < filteredOptions.length - 1 ? 1 : "none",
                borderColor: "divider",
                "&:hover": {
                  bgcolor: "action.hover",
                },
              }}
            >
              {option}
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
