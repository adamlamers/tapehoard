# TapeHoard Design System (THDS)

## 1. Vision & Philosophy
TapeHoard is a high-precision tool for managing massive datasets on physical and cloud media. The design language must reflect **reliability, industrial precision, and information density.** It should feel like a modern piece of mission-control software for a data center, scaled down for the sophisticated homelabber.

---

## 2. Visual Identity

### 2.1 Color Palette (Dark Mode First)
*   **Primary Background:** `#0B0E14` (Deep Space Black)
*   **Secondary Background (Cards/Panels):** `#161B22` (Industrial Slate)
*   **Border / Divider:** `#30363D` (Steel Grey)
*   **Primary Action:** `#3498DB` (Azure Blue)
*   **Success:** `#2ECC71` (Emerald Green)
*   **Warning:** `#F1C40F` (Amber Gold)
*   **Error / Critical:** `#E74C3C` (Alizarin Crimson)
*   **Text (Primary):** `#F0F6FC` (Off-White)
*   **Text (Secondary/Muted):** `#8B949E` (Grey-Blue)

### 2.2 Typography
*   **UI Text:** `Inter` or `Geist Sans` (Clean, highly readable at small sizes).
*   **Data / Code:** `JetBrains Mono` or `Fira Code` (Used for file paths, barcodes, hashes, and logs).
*   **Hierarchy:**
    *   **H1:** 2rem, Bold, High-contrast.
    *   **H2/H3:** 1.5rem / 1.25rem, Semi-bold.
    *   **Body:** 0.95rem, Regular.
    *   **Small/Caption:** 0.8rem, Muted.

---

## 3. UI Components & Patterns

### 3.1 "Glassmorphism 2.0" (Layering)
Use subtle background blurs and semi-transparent overlays for modals and sidebars to create a sense of depth and spatial awareness.
*   *Example:* The Restore Wizard modal should feel "layered" over the dashboard.

### 3.2 Industrial Components
*   **The Tape Progress Bar:** Unlike a standard loading bar, the tape progress bar should have "notched" intervals and a subtle "reel" animation to evoke the feeling of physical media movement.
*   **Media Badges:** Tapes, HDDs, and Cloud buckets should have distinct, high-contrast badges with recognizable icons from Lucide.
*   **FTS Search Bar:** A "Command Palette" style search bar (Cmd+K) that floats in the center of the screen for instant access.

### 3.3 Status Indicators
*   **Pulsing Dots:** Use small pulsing green/amber/red dots for active jobs and hardware status.
*   **Toast Notifications (Sonner):** Sleek, non-intrusive alerts in the bottom-right corner for background completions and hardware events.

### 3.4 Two-Pane Explorer Layout
The File Browser must utilize a classic two-pane architecture to provide a native-feeling management experience:
*   **Navigation Sidebar (Directory Tree):** The left pane contains a persistent, hierarchical tree view of the directory structure. Users can expand/collapse folders and select a directory to populate the right pane.
*   **Detail Pane (File List):** The right pane displays the members (files and sub-directories) of the folder selected in the sidebar. This pane supports sorting, searching, and batch selection.
*   **Interactivity:** Navigation is synchronized; double-clicking a folder in the Detail Pane automatically expands and scrolls to that folder in the Sidebar Tree.

### 3.5 Core File Browser Utility Features
To maintain an enterprise-grade experience, the utility must support:
*   **Multi-Select & Range Selection:** Standard desktop logic (Shift+Click, Ctrl/Cmd+Click).
*   **Column Sorting:** Interactive headers for Name, Size, and Date Modified.
*   **Metadata Detail Pane:** A collapsible right-hand panel for file previews and technical metadata (BLAKE3, storage location).
*   **Keyboard Shortcuts:** Arrow keys for movement, Enter for navigation, Space for tracking toggle.
*   **Visual Status Indicators:** Clear distinct styling for "Tracked", "Excluded", and "Modified" files.

---

## 4. Interaction Language

### 4.1 Tactile Feedback
*   **Buttons:** Subtle scale-down effect (98%) on click to provide a "physical" press sensation.
*   **Transitions:** Use Svelte's `fly` and `fade` transitions for all page navigations and modal entries to make the app feel "alive."

### 4.2 Information Density
*   **Data Grids:** Use compact row heights with clear hover highlighting.
*   **The "Metadata Drawer":** Instead of a separate page, clicking a file in the Virtual Filesystem should slide out a detailed drawer from the right side of the screen, keeping the user in their browsing context.

---

## 5. Iconography (Lucide-Svelte)
*   **Navigation:** `LayoutDashboard`, `Library`, `FolderTree`, `History`, `Settings`.
*   **Actions:** `Database`, `HardDrive`, `CloudDownload`, `Scissors` (for splitting), `Trash2`, `Edit3`.
*   **Status:** `CheckCircle2`, `AlertTriangle`, `XCircle`, `Info`.

---

## 6. Implementation Principles (Vanilla CSS)
*   **Variables:** Define all colors and spacing as CSS variables in `app.css`.
*   **Flexbox/Grid:** Strictly use Modern CSS Layouts (No legacy floats).
*   **Consistency:** Every card, button, and input must strictly adhere to the defined spacing and border-radius (Default: `8px`).
