/**
 * MLInference — ML model configuration accordion content.
 *
 * Shows:
 * - VRAM probe action card
 * - Table of registered models with configuration status
 * - Expandable per-model output label editor
 * - "Mark as Configured" button per model
 */

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";

import { ActionCard, Panel, SectionHeader } from "@shared/components/ui";

import { useMLModels } from "../hooks/useMLModels";

interface MLInferenceProps {
  onVramProbe: () => Promise<void>;
  actionLoading: boolean;
}

export function MLInference({ onVramProbe, actionLoading }: MLInferenceProps) {
  const {
    models,
    loading,
    error,
    expandedModelId,
    handleExpandModel,
    modelOutputs,
    outputsLoading,
    labelEdits,
    handleLabelChange,
    handleSaveLabel,
    savingLabel,
    handleMarkConfigured,
    configuringModel,
  } = useMLModels();

  return (
    <Stack spacing={2.5}>
      {/* VRAM probe */}
      <Panel>
        <SectionHeader title="VRAM Probe" />
        <ActionCard
          label="Re-run VRAM Probe"
          description="Clears stored per-model VRAM measurements. The next worker startup will re-probe all models and record fresh measurements."
          onClick={onVramProbe}
          disabled={actionLoading}
          variant="contained"
          color="primary"
        />
      </Panel>

      {/* Model list */}
      <Panel>
        <SectionHeader title="Registered Models" />
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Configure output labels for each model head before enabling it for
          inference. Known models are pre-labeled automatically at startup.
        </Typography>

        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress size={32} />
          </Box>
        )}

        {error && (
          <Typography color="error" variant="body2">
            {error}
          </Typography>
        )}

        {!loading && !error && models.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No models registered yet. Models are discovered at worker startup.
          </Typography>
        )}

        {!loading && !error && models.length > 0 && (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell />
                  <TableCell>Backbone</TableCell>
                  <TableCell>Head</TableCell>
                  <TableCell>Stem</TableCell>
                  <TableCell align="center">Outputs labeled</TableCell>
                  <TableCell align="center">Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {models.map((model) => {
                  const isExpanded = expandedModelId === model.id;
                  const outputs = modelOutputs[model.id] ?? [];
                  const labeledCount = outputs.filter(
                    (o) => o.fully_labeled
                  ).length;

                  return (
                    <>
                      {/* Summary row */}
                      <TableRow
                        key={model.id}
                        hover
                        sx={{ "& > *": { borderBottom: "unset" } }}
                      >
                        <TableCell sx={{ width: 40, pr: 0 }}>
                          <IconButton
                            size="small"
                            onClick={() => handleExpandModel(model.id)}
                            aria-label={
                              isExpanded ? "collapse" : "expand"
                            }
                          >
                            <ExpandMoreIcon
                              sx={{
                                transform: isExpanded
                                  ? "rotate(180deg)"
                                  : "none",
                                transition: "transform 0.2s",
                              }}
                            />
                          </IconButton>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {model.backbone}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {model.head_type}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ fontFamily: "monospace", fontSize: "0.75rem" }}
                          >
                            {model.model_stem}
                          </Typography>
                        </TableCell>
                        <TableCell align="center">
                          {outputsLoading[model.id] ? (
                            <CircularProgress size={14} />
                          ) : isExpanded ? (
                            <Typography variant="body2">
                              {labeledCount} / {outputs.length}
                            </Typography>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              {model.output_count} total
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell align="center">
                          <Chip
                            label={
                              model.fully_configured
                                ? "Configured"
                                : "Not configured"
                            }
                            color={
                              model.fully_configured ? "success" : "default"
                            }
                            size="small"
                            variant="outlined"
                          />
                        </TableCell>
                      </TableRow>

                      {/* Expanded output editor row */}
                      <TableRow key={`${model.id}-detail`}>
                        <TableCell
                          colSpan={6}
                          sx={{ py: 0, border: isExpanded ? undefined : 0 }}
                        >
                          <Collapse
                            in={isExpanded}
                            timeout="auto"
                            unmountOnExit
                          >
                            <Box sx={{ py: 2, pl: 5 }}>
                              {outputsLoading[model.id] ? (
                                <CircularProgress size={20} />
                              ) : outputs.length === 0 ? (
                                <Typography
                                  variant="body2"
                                  color="text.secondary"
                                >
                                  No outputs registered for this model.
                                </Typography>
                              ) : (
                                <Stack spacing={1.5}>
                                  {outputs.map((output) => (
                                    <Box
                                      key={output.id}
                                      sx={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 1.5,
                                      }}
                                    >
                                      <Typography
                                        variant="body2"
                                        color="text.secondary"
                                        sx={{ minWidth: 28, textAlign: "right" }}
                                      >
                                        [{output.output_index}]
                                      </Typography>
                                      <TextField
                                        size="small"
                                        value={labelEdits[output.id] ?? ""}
                                        onChange={(e) =>
                                          handleLabelChange(
                                            output.id,
                                            e.target.value
                                          )
                                        }
                                        placeholder="Output label"
                                        sx={{ flex: 1, maxWidth: 320 }}
                                        disabled={savingLabel[output.id]}
                                      />
                                      <Button
                                        size="small"
                                        variant="outlined"
                                        onClick={() =>
                                          handleSaveLabel(
                                            model.id,
                                            output.id
                                          )
                                        }
                                        disabled={savingLabel[output.id]}
                                      >
                                        {savingLabel[output.id]
                                          ? "Saving…"
                                          : "Save"}
                                      </Button>
                                      {output.fully_labeled && (
                                        <Chip
                                          label="Labeled"
                                          size="small"
                                          color="success"
                                          variant="outlined"
                                        />
                                      )}
                                    </Box>
                                  ))}

                                  <Box
                                    sx={{
                                      mt: 1,
                                      display: "flex",
                                      gap: 1,
                                      alignItems: "center",
                                    }}
                                  >
                                    <Button
                                      size="small"
                                      variant="contained"
                                      color={
                                        model.fully_configured
                                          ? "warning"
                                          : "success"
                                      }
                                      onClick={() =>
                                        handleMarkConfigured(
                                          model.id,
                                          !model.fully_configured
                                        )
                                      }
                                      disabled={configuringModel[model.id]}
                                    >
                                      {configuringModel[model.id]
                                        ? "Updating…"
                                        : model.fully_configured
                                          ? "Unmark configured"
                                          : "Mark as configured"}
                                    </Button>
                                  </Box>
                                </Stack>
                              )}
                            </Box>
                          </Collapse>
                        </TableCell>
                      </TableRow>
                    </>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Panel>
    </Stack>
  );
}
