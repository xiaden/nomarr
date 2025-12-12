# ServerFilePicker Component

A reusable React + TypeScript component for browsing the filesystem on the Nomarr server and selecting files or directories.

## Features

- **Three selection modes**: File-only, directory-only, or either
- **Server-side browsing**: Navigate the library filesystem without exposing absolute paths
- **Breadcrumb navigation**: Jump to any parent directory in the current path
- **Security**: All paths are relative to the library root, with backend validation
- **Error handling**: Clear error messages for invalid paths or access issues
- **Loading states**: Visual feedback during API calls
- **Clean UI**: Sorted entries (directories first), responsive layout, visual selection feedback

## Usage

### File Selection (mode="file")

```tsx
import { useState } from "react";
import { ServerFilePicker } from "./components/ServerFilePicker";

function MyComponent() {
  const [selectedFile, setSelectedFile] = useState<string>("");

  return (
    <ServerFilePicker
      value={selectedFile}
      onChange={setSelectedFile}
      mode="file"
      label="Select Audio File"
    />
  );
}
```

### Directory Selection (mode="directory")

```tsx
import { useState } from "react";
import { ServerFilePicker } from "./components/ServerFilePicker";

function MyComponent() {
  const [selectedDir, setSelectedDir] = useState<string>("");

  return (
    <ServerFilePicker
      value={selectedDir}
      onChange={setSelectedDir}
      mode="directory"
      label="Select Library Directory"
    />
  );
}
```

### Either File or Directory (mode="either")

```tsx
import { useState } from "react";
import { ServerFilePicker } from "./components/ServerFilePicker";

function MyComponent() {
  const [selectedPath, setSelectedPath] = useState<string>("");

  return (
    <ServerFilePicker
      value={selectedPath}
      onChange={setSelectedPath}
      mode="either"
      label="Select File or Directory"
    />
  );
}
```

## Props

| Prop       | Type                                | Required | Description                                                                                                                                |
| ---------- | ----------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `value`    | `string`                            | Yes      | Current selected path (relative to library root)                                                                                           |
| `onChange` | `(path: string) => void`            | Yes      | Callback when path is selected                                                                                                             |
| `mode`     | `"file" \| "directory" \| "either"` | No       | Selection mode (defaults to "directory"): "file" for files only, "directory" for directories only, "either" for both files and directories |
| `label`    | `string`                            | No       | Optional label to display above picker                                                                                                     |

## Behavior by Mode

### File Mode (`mode="file"`)

- **Directories**: Click to navigate into them
- **Files**: Click to select (calls `onChange` with relative path)
- **"Select This Folder" button**: Hidden

### Directory Mode (`mode="directory"`)

- **Directories**: Click to navigate into them
- **Files**: Not selectable (grayed out, disabled)
- **"Select This Folder" button**: Visible, selects current directory

### Either Mode (`mode="either"`)

- **Directories**: Click to navigate OR use "Select This Folder" button to select
- **Files**: Click to select (calls `onChange` with relative path)
- **"Select This Folder" button**: Visible, selects current directory

## API Integration

The component uses the `api.fs.listFs()` function from `src/shared/api.ts`:

```typescript
import { api } from "../shared/api";

// List directory contents
const response = await api.fs.listFs("music/albums");
// Returns: { path: "music/albums", entries: [{ name: "...", is_dir: true }, ...] }
```

## Backend Endpoint

The component communicates with:

**GET** `/web/api/fs/list?path=<relative_path>`

- **Authentication**: Required (session token)
- **Parameters**:
  - `path` (query string, optional): Relative path from library root
- **Response**: `{ path: string, entries: [{ name: string, is_dir: boolean }] }`
- **Security**:
  - Validates paths against library root
  - Blocks directory traversal attacks
  - Returns relative paths only

## Behavior

### File Mode (`mode="file"`)

- Clicking a **directory** → navigates into it
- Clicking a **file** → selects it and calls `onChange(path)`
- "Select Current Directory" button → hidden

### Directory Mode (`mode="directory"`)

- Clicking a **directory** → selects it and calls `onChange(path)`
- "Select Current Directory" button → visible, selects current directory

### Navigation

- **Breadcrumbs**: Click any segment to jump to that directory
- **Library Root**: Click "Library Root" to return to top level
- **Current path**: Always displayed above entries list

### Error Handling

The component displays errors for:

- Invalid paths
- Directory traversal attempts
- Library not configured (503)
- Path not found (404)
- Network errors

## Styling

The component includes CSS in `ServerFilePicker.css`:

- Clean, minimal design
- Responsive layout
- Hover states for interactive elements
- Clear visual hierarchy (directories vs files)
- Loading, error, and empty states

To customize, override CSS classes:

```css
.server-file-picker {
  /* Container */
}
.breadcrumbs {
  /* Breadcrumb navigation */
}
.entries-list {
  /* Directory listing */
}
.entry-button {
  /* File/directory buttons */
}
.selected-value {
  /* Selected path display */
}
```

## Example Use Cases

1. **Library Configuration**: Let users browse and select their music library directory
2. **File Processing**: Allow users to select specific files for tagging or analysis
3. **Playlist Creation**: Browse and select audio files to add to playlists
4. **Path Input Helper**: Add "Browse..." button next to text inputs for paths

See `ServerFilePickerExamples.tsx` for complete implementation examples.

## Notes

- All paths are **relative to library root** (e.g., `"music/albums/artist"`, not absolute container paths)
- The component requires authentication (session token from login)
- The backend validates all paths to prevent directory traversal
- Entries are sorted: directories first (alphabetically), then files (alphabetically)
