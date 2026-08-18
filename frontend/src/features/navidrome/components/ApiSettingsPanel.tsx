import { ContentCopy, Refresh } from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  IconButton,
  InputAdornment,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { useNotification } from "../../../hooks/useNotification";
import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { getApiKey, regenerateApiKey } from "../../../shared/api/apiKey";
import { ConfirmDialog } from "../../../shared/components/ui";
import {
  getConfig,
  updateConfig,
} from "../../../shared/api/config";
import { pingNavidrome } from "../../../shared/api/navidrome";

const CONFIG_KEYS = {
  url: "navidrome_api_url",
  user: "navidrome_api_user",
  password: "navidrome_api_password",
  prefixMap: "navidrome_path_prefix_map",
} as const;

export function ApiSettingsPanel() {
  const { showSuccess, showError } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } =
    useConfirmDialog();

  // --- Navidrome connection state ---
  const [url, setUrl] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [initialPassword, setInitialPassword] = useState<string | null>(null);
  const [prefixMap, setPrefixMap] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pingResult, setPingResult] = useState<{
    ok: boolean;
    error: string | null;
  } | null>(null);
  const [pinging, setPinging] = useState(false);

  // --- API key state ---
  const [apiKey, setApiKey] = useState("");
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [apiKeyFocused, setApiKeyFocused] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      const config = await getConfig();
      setUrl((config[CONFIG_KEYS.url] as string) ?? "");
      setUser((config[CONFIG_KEYS.user] as string) ?? "");
      const pw = (config[CONFIG_KEYS.password] as string) ?? "";
      setPassword(pw);
      setInitialPassword(pw);
      setPrefixMap((config[CONFIG_KEYS.prefixMap] as string) ?? "");
      setLoaded(true);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to load settings"
      );
    } finally {
      setLoading(false);
    }
  }, [showError]);

  const loadApiKey = useCallback(async () => {
    try {
      setApiKeyLoading(true);
      const res = await getApiKey();
      setApiKey(res.api_key);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to load API key"
      );
    } finally {
      setApiKeyLoading(false);
    }
  }, [showError]);

  const handleRegenerate = async () => {
    const confirmed = await confirm({
      title: "Regenerate API key?",
      message:
        "This will immediately invalidate the current API key and may break existing integrations until they are updated.",
      confirmLabel: "Regenerate",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setRegenerating(true);
      const res = await regenerateApiKey();
      setApiKey(res.api_key);
      showSuccess("API key regenerated");
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to regenerate API key"
      );
    } finally {
      setRegenerating(false);
    }
  };

  const copyApiKey = async () => {
    try {
      await navigator.clipboard.writeText(apiKey);
      showSuccess("API key copied to clipboard");
    } catch {
      showError("Failed to copy to clipboard");
    }
  };

  const saveSettings = async () => {
    try {
      setSaving(true);
      const promises: Promise<unknown>[] = [
        updateConfig(CONFIG_KEYS.url, url),
        updateConfig(CONFIG_KEYS.user, user),
        updateConfig(CONFIG_KEYS.prefixMap, prefixMap),
      ];
      // Only send password if the user explicitly changed it.
      // The backend redacts sensitive values to None, so an empty
      // initial value means "unchanged" — don't overwrite it.
      if (password !== initialPassword) {
        promises.push(updateConfig(CONFIG_KEYS.password, password));
      }
      await Promise.all(promises);
      setInitialPassword(password);
      showSuccess("Navidrome API settings saved");
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to save settings"
      );
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    try {
      setPinging(true);
      setPingResult(null);
      const result = await pingNavidrome();
      setPingResult(result);
      if (result.ok) {
        showSuccess("Navidrome connection successful");
      } else {
        showError(result.error ?? "Connection failed");
      }
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Connection test failed";
      setPingResult({ ok: false, error: msg });
      showError(msg);
    } finally {
      setPinging(false);
    }
  };

  // Load settings + API key on first render.
  useEffect(() => {
    if (!loaded && !loading) {
      void loadSettings();
      void loadApiKey();
    }
  }, [loaded, loading, loadSettings, loadApiKey]);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      {/* --- Nomarr API Key --- */}
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        Nomarr API Key
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Use this key to authenticate external integrations (e.g. the Navidrome
        plugin). Regenerating will invalidate the current key.
      </Typography>

      <Stack direction="row" spacing={1} alignItems="center">
        <TextField
          value={apiKeyLoading ? "Loading..." : apiKey}
          type={apiKeyFocused ? "text" : "password"}
          size="small"
          fullWidth
          onFocus={() => setApiKeyFocused(true)}
          onBlur={() => setApiKeyFocused(false)}
          slotProps={{
            input: {
              readOnly: true,
              sx: { fontFamily: "monospace", fontSize: "0.85rem" },
              endAdornment: (
                <InputAdornment position="end">
                  <Tooltip title="Copy to clipboard">
                    <IconButton
                      onClick={() => void copyApiKey()}
                      disabled={!apiKey}
                      edge="end"
                      size="small"
                    >
                      <ContentCopy fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </InputAdornment>
              ),
            },
          }}
        />
        <Tooltip title="Regenerate API key">
          <span>
            <Button
              variant="outlined"
              color="warning"
              onClick={() => void handleRegenerate()}
              disabled={regenerating}
              size="small"
              startIcon={
                regenerating ? (
                  <CircularProgress size={16} />
                ) : (
                  <Refresh />
                )
              }
              sx={{ whiteSpace: "nowrap" }}
            >
              Regenerate
            </Button>
          </span>
        </Tooltip>
      </Stack>

      <Divider sx={{ my: 1 }} />

      {/* --- Navidrome Connection --- */}
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        Navidrome Connection
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Configure the Navidrome Subsonic API connection for playlist push,
        library rescan, and similar track features.
      </Typography>

      <TextField
        label="Navidrome API URL"
        placeholder="http://navidrome:4533"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        size="small"
        fullWidth
        helperText="Base URL of your Navidrome server"
      />

      <TextField
        label="Username"
        value={user}
        onChange={(e) => setUser(e.target.value)}
        size="small"
        fullWidth
      />

      <TextField
        label="Password"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        size="small"
        fullWidth
      />

      <TextField
        label="Path Prefix Map"
        placeholder="/music:/media/music"
        value={prefixMap}
        onChange={(e) => setPrefixMap(e.target.value)}
        size="small"
        fullWidth
        helperText="Comma-separated from:to pairs for path remapping. Leave empty to use auto-detection."
      />

      <Stack direction="row" spacing={2} alignItems="center">
        <Button
          variant="contained"
          onClick={() => void saveSettings()}
          disabled={saving}
          size="small"
        >
          {saving ? "Saving..." : "Save"}
        </Button>

        <Button
          variant="outlined"
          onClick={() => void testConnection()}
          disabled={pinging || !url}
          size="small"
        >
          {pinging ? (
            <>
              <CircularProgress size={16} sx={{ mr: 1 }} />
              Testing...
            </>
          ) : (
            "Test Connection"
          )}
        </Button>
      </Stack>

      {pingResult && (
        <Alert severity={pingResult.ok ? "success" : "error"}>
          {pingResult.ok
            ? "Connected to Navidrome successfully"
            : `Connection failed: ${pingResult.error ?? "Unknown error"}`}
        </Alert>
      )}

      <ConfirmDialog
        open={isOpen}
        title={options.title}
        message={options.message}
        confirmLabel={options.confirmLabel}
        cancelLabel={options.cancelLabel}
        severity={options.severity}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />

    </Stack>
  );
}
