/**
 * Custom hook for ML model configuration management.
 *
 * Fetches registered models, manages per-model output expansion,
 * label editing, save/configure actions, and loading/error state.
 */

import { useCallback, useEffect, useState } from "react";

import { useNotification } from "../../../hooks/useNotification";
import {
  type MlModel,
  type MlModelOutput,
  getModelOutputs,
  listModels,
  markModelConfigured,
  updateOutputLabel,
} from "../../../shared/api/ml";

/** Draft label edits keyed by output id. */
type LabelEdits = Record<string, string>;

export function useMLModels() {
  const { showSuccess, showError } = useNotification();

  // --- model list ---
  const [models, setModels] = useState<MlModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // --- expanded model / outputs ---
  const [expandedModelId, setExpandedModelId] = useState<string | null>(null);
  const [modelOutputs, setModelOutputs] = useState<Record<string, MlModelOutput[]>>({});
  const [outputsLoading, setOutputsLoading] = useState<Record<string, boolean>>({});

  // --- label editing ---
  const [labelEdits, setLabelEdits] = useState<LabelEdits>({});
  const [savingLabel, setSavingLabel] = useState<Record<string, boolean>>({});

  // --- model configure toggle ---
  const [configuringModel, setConfiguringModel] = useState<Record<string, boolean>>({});

  // -----------------------------------------------------------------------
  // Load model list
  // -----------------------------------------------------------------------
  const loadModels = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listModels();
      setModels(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load models";
      setError(msg);
      console.error("[useMLModels] Load error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  // -----------------------------------------------------------------------
  // Expand / collapse a model row to show its outputs
  // -----------------------------------------------------------------------
  const handleExpandModel = useCallback(
    async (modelId: string) => {
      // Collapse if already expanded
      if (expandedModelId === modelId) {
        setExpandedModelId(null);
        return;
      }

      setExpandedModelId(modelId);

      // Fetch outputs if not already cached
      if (modelOutputs[modelId]) return;

      setOutputsLoading((prev) => ({ ...prev, [modelId]: true }));
      try {
        const outputs = await getModelOutputs(modelId);
        setModelOutputs((prev) => ({ ...prev, [modelId]: outputs }));

        // Pre-populate label edits with current DB values
        const edits: LabelEdits = {};
        for (const output of outputs) {
          edits[output.id] = output.label ?? "";
        }
        setLabelEdits((prev) => ({ ...prev, ...edits }));
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to load model outputs"
        );
        setExpandedModelId(null);
      } finally {
        setOutputsLoading((prev) => ({ ...prev, [modelId]: false }));
      }
    },
    [expandedModelId, modelOutputs, showError]
  );

  // -----------------------------------------------------------------------
  // Label editing
  // -----------------------------------------------------------------------
  const handleLabelChange = useCallback((outputId: string, value: string) => {
    setLabelEdits((prev) => ({ ...prev, [outputId]: value }));
  }, []);

  const handleSaveLabel = useCallback(
    async (modelId: string, outputId: string) => {
      const label = labelEdits[outputId]?.trim();
      if (!label) {
        showError("Label cannot be empty");
        return;
      }

      setSavingLabel((prev) => ({ ...prev, [outputId]: true }));
      try {
        await updateOutputLabel(modelId, outputId, { label });

        // Update cached outputs so the saved label is reflected immediately
        setModelOutputs((prev) => {
          const current = prev[modelId];
          if (!current) return prev;
          return {
            ...prev,
            [modelId]: current.map((o) =>
              o.id === outputId
                ? { ...o, label, fully_labeled: true }
                : o
            ),
          };
        });

        showSuccess("Label saved");
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to save label"
        );
      } finally {
        setSavingLabel((prev) => ({ ...prev, [outputId]: false }));
      }
    },
    [labelEdits, showError, showSuccess]
  );

  // -----------------------------------------------------------------------
  // Mark model configured / unconfigured
  // -----------------------------------------------------------------------
  const handleMarkConfigured = useCallback(
    async (modelId: string, value: boolean) => {
      setConfiguringModel((prev) => ({ ...prev, [modelId]: true }));
      try {
        await markModelConfigured(modelId, { value });

        // Optimistically update the local model list
        setModels((prev) =>
          prev.map((m) =>
            m.id === modelId ? { ...m, fully_configured: value } : m
          )
        );

        showSuccess(
          value ? "Model marked as configured" : "Model marked as unconfigured"
        );
      } catch (err) {
        showError(
          err instanceof Error ? err.message : "Failed to update model"
        );
      } finally {
        setConfiguringModel((prev) => ({ ...prev, [modelId]: false }));
      }
    },
    [showError, showSuccess]
  );

  return {
    // model list
    models,
    loading,
    error,
    reload: loadModels,
    // expansion
    expandedModelId,
    handleExpandModel,
    modelOutputs,
    outputsLoading,
    // label editing
    labelEdits,
    handleLabelChange,
    handleSaveLabel,
    savingLabel,
    // configure
    handleMarkConfigured,
    configuringModel,
  };
}
