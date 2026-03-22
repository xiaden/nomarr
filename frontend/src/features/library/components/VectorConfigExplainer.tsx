import { Alert, Typography } from "@mui/material";

interface VectorConfigExplainerProps {
  totalTracks: number;
  groupSize: number;
  thoroughness: number;
}

export function VectorConfigExplainer({
  totalTracks,
  groupSize,
  thoroughness,
}: VectorConfigExplainerProps) {
  if (totalTracks === 0) {
    return (
      <Alert severity="info" sx={{ mt: 1 }}>
        No vectors found yet. Configure settings now — they&apos;ll take effect after your next scan and
        promote.
      </Alert>
    );
  }

  const nLists = Math.min(4000, Math.max(10, Math.floor(totalTracks / groupSize)));
  const nProbe = Math.max(1, Math.floor((nLists * thoroughness) / 100));
  const songsChecked = Math.min(nProbe * groupSize, totalTracks);
  const pctSearched = Math.min(100, (songsChecked / totalTracks) * 100);

  return (
    <Alert severity="info" sx={{ mt: 1 }}>
      <Typography variant="body2">
        With <strong>{totalTracks.toLocaleString()}</strong> songs and a group size of{" "}
        <strong>{groupSize}</strong>, your library is divided into{" "}
        <strong>{nLists.toLocaleString()}</strong> similarity neighborhoods (~{groupSize} songs each).
      </Typography>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        At <strong>{thoroughness}%</strong> thoroughness, each search checks ~
        <strong>{songsChecked.toLocaleString()}</strong> songs across <strong>{nProbe}</strong>{" "}
        neighborhoods (about <strong>{pctSearched.toFixed(1)}%</strong> of your library).
      </Typography>
    </Alert>
  );
}
